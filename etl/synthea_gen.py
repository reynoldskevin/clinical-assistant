"""Synthea synthetic-patient cohort generation via Docker.

Builds the ``docker run`` invocation for the Synthea generator and executes it
through an injectable runner, returning the generated patient FHIR bundles.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional


# Pinned public Synthea image (InterSystems Developer Community image,
# from GitHub repo intersystems-community/irisdemo-base-synthea).
SYNTHEA_IMAGE = "intersystemsdc/irisdemo-base-synthea:version-1.3.4"
# Mount point inside the container that Synthea writes its output to.
CONTAINER_OUTPUT_DIR = "/output"


class SyntheaError(Exception):
    """Raised when Synthea generation fails or produces no patient bundles."""


def build_synthea_command(
    count: int,
    output_dir: Path | str,
    seed: Optional[int] = None,
) -> list[str]:
    """Build the ``docker run`` argv for a Synthea generation run.

    The host ``output_dir`` is bind-mounted into the container, FHIR export is
    enabled, and the requested patient count is passed through. The random seed
    is included only when explicitly provided.
    """
    cmd: list[str] = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{output_dir}:{CONTAINER_OUTPUT_DIR}",
        SYNTHEA_IMAGE,
        "-p",
        str(count),
        "--exporter.fhir.export",
        "true",
        "--exporter.baseDirectory",
        CONTAINER_OUTPUT_DIR,
    ]
    if seed is not None:
        cmd += ["-s", str(seed)]
    return cmd


def generate_cohort(
    count: int,
    output_dir: Path | str,
    *,
    seed: Optional[int] = None,
    runner: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
) -> list[Path]:
    """Generate a Synthea cohort and return the patient FHIR bundle paths.

    Creates ``output_dir``, runs the built command via ``runner``, then collects
    the patient bundles from ``<output_dir>/fhir/*.json``, excluding the
    non-patient ``hospitalInformation*`` and ``practitionerInformation*`` files.

    Raises ``SyntheaError`` on a non-zero exit code, or when the run succeeds but
    produces no patient bundles.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cmd = build_synthea_command(count, output_path, seed=seed)
    result = runner(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise SyntheaError(
            f"Synthea generation failed with exit code {result.returncode}"
        )

    bundles = [
        path
        for path in sorted((output_path / "fhir").glob("*.json"))
        if not path.name.startswith(("hospitalInformation", "practitionerInformation"))
    ]

    if not bundles:
        raise SyntheaError("Synthea run succeeded but produced no patient bundles")

    return bundles
