"""Production wiring for the sidecar: real Anthropic message-creator + HTTP boundary.

Kept separate from ``agent.py`` so the agent itself stays SDK-free and
unit-testable. This module is the only place the anthropic SDK and network I/O
live. Both builders are dependency-injectable (``client`` / ``opener``) so they
can be exercised in tests without a live API call or a running OpenEMR.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from typing import Any, Callable

from contracts import (
    DocumentMetadata,
    EmptyToolInput,
    EncounterRow,
    GetEncounterInput,
    GetIntakeFactInput,
    GetMedicationsInput,
    LabResult,
    MedicationRow,
    NoteSnippet,
    PatientSummary,
    SearchChartInput,
    validate_obj,
    validate_rows,
)

# The intake-form fields exposed as individually-citable rows, in the order the
# co-pilot most often needs them (chief_concern first). Kept in sync with the
# groundable fields on ``contracts.IntakeFact``.
_INTAKE_FIELDS = (
    "chief_concern",
    "demographics",
    "current_medications",
    "allergies",
    "family_history",
)


def new_correlation_id() -> str:
    """Return a unique, non-empty correlation id for one agent invocation."""
    return uuid.uuid4().hex


def build_message_creator(
    api_key: str | None = None,
    *,
    client: Any = None,
    model: str = "claude-opus-4-8",
) -> Callable[..., Any]:
    """Return a message-creator backed by the Anthropic SDK.

    The returned callable matches the signature ``ClaudeAgent`` expects
    (``model=``, ``max_tokens=``, ``system=``, ``tools=``, ``messages=``) and
    returns the SDK ``Message`` object unchanged (``.content`` / ``.usage`` /
    ``.stop_reason``). The anthropic SDK is imported lazily so importing this
    module — or the agent — never requires the SDK to be installed.
    """
    if client is None:
        import anthropic  # lazy: only needed when actually talking to the API

        client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
        )

        # Optional Braintrust observability: when a key is configured, wrap the
        # client so every Claude call is auto-logged (inputs, outputs, tokens,
        # cost, latency). Guarded so observability can never break the agent path.
        if os.environ.get("BRAINTRUST_API_KEY"):
            try:
                from braintrust import init_logger, wrap_anthropic

                init_logger(project=os.environ.get("BRAINTRUST_PROJECT", "oe-ai-agent"))
                client = wrap_anthropic(client)
            except Exception:  # noqa: BLE001 - never let telemetry wiring fail the request path
                logging.getLogger("sidecar").exception("Braintrust init failed; continuing without it")

    def create(**kwargs: Any) -> Any:
        kwargs.setdefault("model", model)
        return client.messages.create(**kwargs)

    return create


def build_tracer() -> Any:
    """Return a tracer that wraps each agent turn in a Braintrust span.

    Returns a :class:`NullTracer` (zero-overhead, no braintrust import) unless
    ``BRAINTRUST_API_KEY`` is set. When it is, a Braintrust-backed tracer is
    returned whose ``turn(metadata)`` opens a ``braintrust`` span carrying that
    metadata as a context manager, so the ``wrap_anthropic`` model calls nest
    under it (grouping the conversation by ``conversation_id`` + ``pid``).

    Fully guarded, mirroring ``build_message_creator``: any import or runtime
    error while wiring braintrust degrades to a :class:`NullTracer`, so
    observability can never break the request path.
    """
    from observability import NullTracer

    if not os.environ.get("BRAINTRUST_API_KEY"):
        return NullTracer()

    try:
        import braintrust

        # Idempotent: safe to call on every build. Initialises the logger the
        # spans attach to (the same project the wrapped client logs into).
        braintrust.init_logger(project=os.environ.get("BRAINTRUST_PROJECT", "oe-ai-agent"))

        class _BraintrustTracer:
            """Opens a braintrust span per turn, carrying the turn metadata."""

            def turn(self, metadata: dict[str, Any]) -> Any:
                try:
                    return braintrust.start_span(name="agent-turn", metadata=metadata)
                except Exception:  # noqa: BLE001 - a span op must never break the turn
                    logging.getLogger("sidecar").exception("Braintrust span failed; continuing without it")
                    import contextlib

                    return contextlib.nullcontext()

        return _BraintrustTracer()
    except Exception:  # noqa: BLE001 - never let telemetry wiring fail the request path
        logging.getLogger("sidecar").exception("Braintrust tracer init failed; continuing without it")
        return NullTracer()


def build_boundary(
    summary_url: str,
    jwt: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 15.0,
    correlation_id: str | None = None,
) -> Callable[[int], dict[str, Any]]:
    """Return a boundary callable that fetches the patient summary over HTTP.

    The scoped JWT is forwarded as a Bearer token; the OpenEMR boundary verifies
    it (pid scope, audience, expiry) before returning any chart data. A non-2xx
    response makes ``opener`` raise, which the agent surfaces to the model as a
    tool error rather than crashing the loop.
    """

    def boundary(pid: int) -> dict[str, Any]:
        payload = json.dumps({"pid": pid}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt}",
        }
        if correlation_id is not None:
            headers["X-Correlation-ID"] = correlation_id
        request = urllib.request.Request(
            summary_url,
            data=payload,
            method="POST",
            headers=headers,
        )
        with opener(request, timeout=timeout) as response:
            body = response.read()

        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("boundary returned a non-object summary")
        # Validate the get_patient_summary output against its contract (raises on
        # a contract violation); returns the original dict unchanged (lossless).
        return validate_obj(PatientSummary, parsed)

    return boundary


class ChartBoundary:
    """Operation-dispatched HTTP chart boundary.

    Each method POSTs ``{op, pid, params}`` to read.php with the forwarded Bearer
    JWT; the OpenEMR boundary verifies it (pid scope, audience, expiry) before
    returning any chart data. A non-2xx response makes ``opener`` raise, which
    the agent surfaces to the model as a tool error rather than crashing the loop.
    """

    def __init__(
        self,
        base_url: str,
        jwt: str,
        *,
        opener: Callable[..., Any],
        timeout: float,
        correlation_id: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._jwt = jwt
        self._opener = opener
        self._timeout = timeout
        self._correlation_id = correlation_id

    def _post(self, op: str, pid: int, params: dict[str, Any]) -> dict[str, Any] | list[Any]:
        payload = json.dumps({"op": op, "pid": pid, "params": params}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._jwt}",
        }
        if self._correlation_id is not None:
            headers["X-Correlation-ID"] = self._correlation_id
        request = urllib.request.Request(
            self._base_url,
            data=payload,
            method="POST",
            headers=headers,
        )
        with self._opener(request, timeout=self._timeout) as response:
            body = response.read()

        parsed = json.loads(body)
        # read.php returns the provider result directly: an object for summary /
        # get_encounter, and a bare ARRAY for list_encounters / get_results /
        # get_medications / search_chart. Accept both — a JSON scalar
        # (string/number/null) would be the unexpected case.
        if not isinstance(parsed, (dict, list)):
            raise ValueError("chart boundary returned an unexpected result type")
        return parsed

    def summary(self, pid: int) -> dict[str, Any]:
        result = self._post("summary", pid, {})
        if not isinstance(result, dict):
            raise ValueError("summary result must be an object")
        return result

    def list_encounters(self, pid: int) -> list[Any]:
        result = self._post("list_encounters", pid, {})
        if not isinstance(result, list):
            raise ValueError("list_encounters result must be an array")
        return result

    def get_encounter(self, pid: int, encounter_id: int) -> dict[str, Any]:
        result = self._post("get_encounter", pid, {"encounter_id": encounter_id})
        if not isinstance(result, dict):
            raise ValueError("get_encounter result must be an object")
        return result

    def get_results(self, pid: int) -> list[Any]:
        result = self._post("get_results", pid, {})
        if not isinstance(result, list):
            raise ValueError("get_results result must be an array")
        return result

    def get_medications(self, pid: int, active_only: bool = False) -> list[Any]:
        result = self._post("get_medications", pid, {"active_only": active_only})
        if not isinstance(result, list):
            raise ValueError("get_medications result must be an array")
        return result

    def search_chart(self, pid: int, query: str, limit: int = 20) -> list[Any]:
        result = self._post("search_chart", pid, {"query": query, "limit": limit})
        if not isinstance(result, list):
            raise ValueError("search_chart result must be an array")
        return result

    def get_documents(self, pid: int) -> list[Any]:
        result = self._post("get_documents", pid, {})
        if not isinstance(result, list):
            raise ValueError("get_documents result must be an array")
        return result

    def get_document(self, pid: int, document_id: int) -> dict[str, Any]:
        result = self._post("get_document", pid, {"document_id": document_id})
        if not isinstance(result, dict):
            raise ValueError("get_document result must be an object")
        return result


def build_chart_boundary(
    base_url: str,
    jwt: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 15.0,
    correlation_id: str | None = None,
) -> ChartBoundary:
    """Return an operation-dispatched chart boundary bound to ``base_url``/``jwt``.

    Exposes ``.summary(pid)`` / ``.list_encounters(pid)`` /
    ``.get_encounter(pid, encounter_id)``, each POSTing the matching ``op`` to
    read.php with the forwarded Bearer JWT.
    """
    return ChartBoundary(base_url, jwt, opener=opener, timeout=timeout, correlation_id=correlation_id)


def build_encounter_tools(chart_boundary: ChartBoundary) -> list[dict[str, Any]]:
    """Turn a chart boundary into the encounter-navigation ToolSpecs.

    Each spec is ``{name, description, input_schema, handler(pid, tool_input)}``.
    The handlers dispatch to the boundary with the session pid; get_encounter
    additionally requires a model-supplied ``encounter_id``.
    """
    return [
        {
            "name": "list_encounters",
            "description": (
                "List the current patient's encounters (visits), most recent "
                "first, with each encounter's id, date, and reason. Takes no "
                "arguments: the patient is fixed for this session."
            ),
            "input_schema": EmptyToolInput.model_json_schema(),
            "handler": lambda pid, inp: validate_rows(
                EncounterRow, chart_boundary.list_encounters(pid)
            ),
        },
        {
            "name": "get_encounter",
            "description": (
                "Retrieve the detail of a single encounter (visit) for the "
                "current patient by its encounter id. Use list_encounters first "
                "to find the id."
            ),
            "input_schema": GetEncounterInput.model_json_schema(),
            "handler": lambda pid, inp: validate_obj(
                EncounterRow,
                chart_boundary.get_encounter(
                    pid, GetEncounterInput.model_validate(inp).encounter_id
                ),
            ),
        },
    ]


def build_documents_tools(chart_boundary: ChartBoundary) -> list[dict[str, Any]]:
    """Turn a chart boundary into the document-listing ToolSpec.

    Returns a single ``get_documents`` no-argument list tool: it lists the
    current patient's uploaded documents (id, name, type, date) as metadata —
    never the document blob. The patient is fixed for this session, so the tool
    takes no arguments. The handler validates each metadata row against the
    ``DocumentMetadata`` contract before returning it.
    """
    return [
        {
            "name": "get_documents",
            "description": (
                "List the current patient's uploaded documents (lab PDFs and "
                "intake forms) — each with its id, name, doc_type, and date. "
                "Metadata only; never the document contents. Takes no arguments: "
                "the patient is fixed for this session."
            ),
            "input_schema": EmptyToolInput.model_json_schema(),
            "handler": lambda pid, inp: validate_rows(
                DocumentMetadata, chart_boundary.get_documents(pid)
            ),
        },
    ]


def build_intake_tool(
    chart_boundary: ChartBoundary,
    message_creator: Callable[..., Any],
    model: str = "claude-opus-4-8",
) -> dict[str, Any]:
    """Turn a chart boundary + VLM into the intake-form extraction ToolSpec.

    ``get_documents`` returns intake-form *metadata* only; the extracted intake
    facts (chief concern, demographics, medications, allergies, family history)
    live in the document blob, which no other ``/ask`` tool can read. This tool
    bridges that gap: it fetches the patient's intake form pid-scoped through the
    same read boundary the upload-time extractor uses, runs the VLM extractor
    (``attach_and_extract``), and returns each grounded field as its own row —
    ``ref``/``title``/``section``/``value`` — so the model can cite an intake
    fact (e.g. ``intake:<id>:chief_concern``) the same way it cites any record
    fact. An ungroundable field is dropped, never invented; when the patient has
    no intake form on file the tool returns an empty list.

    Requires the same injected VLM ``message_creator`` the extract endpoint uses,
    so this is built where that dependency is available (``default_agent_builder``),
    unlike the boundary-only tool builders above.
    """
    # Lazy import keeps factory importable without the extractor's transitive deps
    # and mirrors how graph.py defers the same module.
    from extractor import attach_and_extract

    def handler(pid: int, inp: dict[str, Any]) -> list[dict[str, Any]]:
        parsed = GetIntakeFactInput.model_validate(inp)
        # Resolve the target intake form pid-scoped: only the patient's own
        # documents are ever visible here, so a model-supplied document_id can
        # never redirect the read to another chart. get_documents is newest-first.
        documents = chart_boundary.get_documents(pid)
        intake_docs = [
            d for d in documents
            if isinstance(d, dict) and str(d.get("doc_type")) == "intake_form"
        ]
        if parsed.document_id is not None:
            intake_docs = [
                d for d in intake_docs if int(d.get("id") or 0) == parsed.document_id
            ]
        if not intake_docs:
            # No intake form on file (or the requested id is not one): an empty
            # result the model reads as "not documented", never a fabricated fact.
            return []

        document_id = int(intake_docs[0]["id"])
        result = attach_and_extract(
            pid,
            document_id,
            "intake_form",
            chart_boundary=chart_boundary,
            message_creator=message_creator,
            model=model,
        )
        fact = result.fact

        # One grounded row per non-null field so each intake fact is individually
        # citable. section/title/value map onto the record-citation the gate
        # synthesizes (page_or_section / field_or_chunk_id / quote_or_value).
        rows: list[dict[str, Any]] = []
        for field in _INTAKE_FIELDS:
            value = getattr(fact, field, None)
            if value is None:
                continue
            rows.append(
                {
                    "ref": f"intake:{document_id}:{field}",
                    "title": field,
                    "section": fact.source_citation,
                    "value": value,
                }
            )
        return rows

    return {
        "name": "get_intake_form",
        "description": (
            "Extract the structured facts from the current patient's uploaded "
            "intake form — chief_concern, demographics, current_medications, "
            "allergies, and family_history — each as a citable row with a ref, "
            "the field name, the source citation, and the extracted value. Use "
            "this to answer questions about what the patient reported on their "
            "intake form (get_documents only lists that the form exists, not its "
            "contents). Optionally pass a document_id (from get_documents) to "
            "target a specific intake form; omit it to use the most recent one. "
            "Returns an empty list when the patient has no intake form on file. "
            "The patient is fixed for this session."
        ),
        "input_schema": GetIntakeFactInput.model_json_schema(),
        "handler": handler,
    }


def build_results_tool(chart_boundary: ChartBoundary) -> dict[str, Any]:
    """Turn a chart boundary into the lab/diagnostic-results ToolSpec.

    A single ``{name, description, input_schema, handler(pid, tool_input)}`` dict.
    The handler dispatches to the boundary with the fixed session pid; the model
    supplies no arguments (the patient is fixed for this session).
    """
    return {
        "name": "get_results",
        "description": (
            "Retrieve the current patient's lab and diagnostic results — each "
            "result's value, units, reference range, abnormal flag, status, and "
            "date. A complete results view, distinct from the summary's capped "
            "recent labs. Takes no arguments: the patient is fixed for this "
            "session."
        ),
        "input_schema": EmptyToolInput.model_json_schema(),
        "handler": lambda pid, inp: validate_rows(
            LabResult, chart_boundary.get_results(pid)
        ),
    }


def build_medications_tool(chart_boundary: ChartBoundary) -> dict[str, Any]:
    """Turn a chart boundary into the medications ToolSpec.

    A single ``{name, description, input_schema, handler(pid, tool_input)}`` dict.
    The handler dispatches to the boundary with the fixed session pid; the model
    may optionally supply ``active_only`` to restrict the list to active meds.
    Each returned row carries a ``status_conflict`` "stale-active" data-quality
    flag — a row flagged active whose end date has already passed — so the model
    can hedge rather than blindly trust the active flag.
    """
    return {
        "name": "get_medications",
        "description": (
            "Retrieve the current patient's medications (prescriptions and "
            "medication-list entries) — each with its drug name, rxnorm code, "
            "active flag, start/end dates, and a status_conflict flag that is "
            "true when a medication is marked active yet its end date has already "
            "passed (a possibly-stale record to hedge on). Pass active_only=true "
            "to list only active medications. The patient is fixed for this "
            "session."
        ),
        "input_schema": GetMedicationsInput.model_json_schema(),
        "handler": lambda pid, inp: validate_rows(
            MedicationRow,
            chart_boundary.get_medications(
                pid, GetMedicationsInput.model_validate(inp).active_only
            ),
        ),
    }


def build_search_tool(chart_boundary: ChartBoundary) -> dict[str, Any]:
    """Turn a chart boundary into the free-text note-search ToolSpec.

    A single ``{name, description, input_schema, handler(pid, tool_input)}`` dict.
    The handler dispatches to the boundary with the fixed session pid; the model
    must supply a ``query`` and may optionally supply a ``limit`` (default 20).
    Results are snippet rows from the patient's notes — never whole documents —
    so the model can quote grounded narrative content the structured tools omit.
    """
    return {
        "name": "search_chart",
        "description": (
            "Full-text search over the current patient's free-text clinical "
            "notes (progress notes and SOAP notes). Returns snippet rows — each "
            "with a ref, source_type, date, and a short snippet of matching "
            "text, never the whole document — most recent first. Use this for "
            "narrative content the structured tools do not expose. Supply a "
            "'query' to search for; 'limit' is optional (default 20). The "
            "patient is fixed for this session."
        ),
        "input_schema": SearchChartInput.model_json_schema(),
        "handler": lambda pid, inp: validate_rows(
            NoteSnippet,
            (lambda a: chart_boundary.search_chart(pid, a.query, a.limit))(
                SearchChartInput.model_validate(inp)
            ),
        ),
    }
