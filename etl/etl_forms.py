"""Synthea FHIR bundle -> OpenEMR encounter-form registration ETL (T05b).

register_forms() is a post-pass over data already loaded by the patient,
encounter, and observation ETLs (T02/T03/T05). For each bundle it links the
already-loaded form_vitals and procedure_order rows to their OpenEMR encounters
via the `forms` registry so the encounter UI renders them.

Both paths are idempotent: a `forms` row keyed by (formdir, form_id[, pid]) is
inserted only once.
"""

from etl_observations import (
    _category_codes,
    _find_patient_uuid,
    _iter_resources,
    _loinc_code,
    _parse_datetime,
)


def _extract_uuid(reference):
    """Extract the bare id from 'urn:uuid:<id>' or 'Encounter/<id>'."""
    if not reference:
        return ""
    if reference.startswith("urn:uuid:"):
        return reference[len("urn:uuid:"):]
    if "/" in reference:
        return reference.rsplit("/", 1)[-1]
    return reference


def _resolve_encounter(obs, cur):
    """Resolve an Observation's encounter reference to an OpenEMR encounter number.

    Returns the encounter number, or None if there is no reference or the
    referenced form_encounter row does not exist.
    """
    reference = (obs.get("encounter") or {}).get("reference", "")
    enc_uuid = _extract_uuid(reference)
    if not enc_uuid:
        return None
    cur.execute(
        "SELECT encounter FROM form_encounter "
        "WHERE uuid = UNHEX(REPLACE(%s, '-', '')) LIMIT 1",
        (enc_uuid,),
    )
    row = cur.fetchone()
    return row[0] if row is not None else None


def _register_vitals(bundle, pid, cur):
    inserted = 0

    groups = {}
    for obs in _iter_resources(bundle, "Observation"):
        if "vital-signs" not in _category_codes(obs):
            continue
        date = _parse_datetime(obs.get("effectiveDateTime", ""))
        groups.setdefault(date, []).append(obs)

    for date, observations in groups.items():
        encounter = None
        for obs in observations:
            encounter = _resolve_encounter(obs, cur)
            if encounter is not None:
                break
        if encounter is None:
            continue

        cur.execute(
            "SELECT id FROM form_vitals WHERE pid = %s AND date = %s LIMIT 1",
            (pid, date),
        )
        row = cur.fetchone()
        if row is None:
            continue
        form_id = row[0]

        cur.execute(
            "SELECT 1 FROM forms "
            "WHERE formdir = 'vitals' AND form_id = %s AND pid = %s LIMIT 1",
            (form_id, pid),
        )
        if cur.fetchone() is not None:
            continue

        cur.execute(
            "INSERT INTO forms "
            "(formdir, form_name, form_id, pid, encounter, date, deleted) "
            "VALUES ('vitals', 'Vitals', %s, %s, %s, %s, 0)",
            (form_id, pid, encounter, date),
        )
        inserted += 1

    return inserted


def _register_labs(bundle, pid, cur):
    inserted = 0

    for obs in _iter_resources(bundle, "Observation"):
        if "laboratory" not in _category_codes(obs):
            continue

        result_code = _loinc_code(obs.get("code") or {})
        date = _parse_datetime(obs.get("effectiveDateTime", ""))

        encounter = _resolve_encounter(obs, cur)
        if encounter is None:
            continue

        cur.execute(
            "SELECT po.procedure_order_id FROM procedure_result pr "
            "JOIN procedure_report prpt "
            "ON prpt.procedure_report_id = pr.procedure_report_id "
            "JOIN procedure_order po "
            "ON po.procedure_order_id = prpt.procedure_order_id "
            "WHERE po.patient_id = %s AND pr.result_code = %s AND pr.date = %s "
            "LIMIT 1",
            (pid, result_code, date),
        )
        row = cur.fetchone()
        if row is None:
            continue
        order_id = row[0]

        cur.execute(
            "SELECT 1 FROM forms "
            "WHERE formdir = 'procedure_order' AND form_id = %s LIMIT 1",
            (order_id,),
        )
        if cur.fetchone() is not None:
            continue

        cur.execute(
            "UPDATE procedure_order SET encounter_id = %s "
            "WHERE procedure_order_id = %s",
            (encounter, order_id),
        )

        cur.execute(
            "INSERT INTO forms "
            "(formdir, form_name, form_id, pid, encounter, date, deleted) "
            "VALUES ('procedure_order', 'Procedure Order', %s, %s, %s, %s, 0)",
            (order_id, pid, encounter, date),
        )
        inserted += 1

    return inserted


def register_forms(bundles, conn):
    counts = {"vitals": 0, "labs": 0}
    cur = conn.cursor()

    for bundle in bundles:
        patient_uuid = _find_patient_uuid(bundle)
        if not patient_uuid:
            continue

        cur.execute(
            "SELECT pid FROM patient_data WHERE uuid = UNHEX(REPLACE(%s, '-', '')) LIMIT 1",
            (patient_uuid,),
        )
        row = cur.fetchone()
        if row is None:
            continue
        pid = row[0]

        counts["vitals"] += _register_vitals(bundle, pid, cur)
        counts["labs"] += _register_labs(bundle, pid, cur)

    return counts
