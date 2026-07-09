"""T01 acceptance tests (LOCKED contract) for the Synthea generation wrapper.

Unit tests only — the docker/Synthea runner is injected and mocked, so the loop
is fast and deterministic. A real run lives behind the `integration` mark (T02).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from synthea_gen import build_synthea_command, generate_cohort, SyntheaError


def test_build_command_is_docker_run_with_count_and_fhir(tmp_path):
    cmd = build_synthea_command(5, tmp_path)
    assert cmd[:2] == ["docker", "run"]
    assert "--rm" in cmd
    # output dir is bind-mounted (host:container form)
    assert any(f"{tmp_path}:" in part for part in cmd), cmd
    # a Synthea image is referenced
    assert any("synthea" in part.lower() for part in cmd), cmd
    # requested patient count is present
    assert "5" in cmd, cmd
    # FHIR export is enabled
    assert any("fhir.export" in part for part in cmd), cmd
    assert "true" in cmd, cmd


def test_build_command_includes_seed_when_provided(tmp_path):
    cmd = build_synthea_command(3, tmp_path, seed=42)
    assert "42" in cmd, cmd


def test_build_command_omits_seed_when_none(tmp_path):
    cmd = build_synthea_command(3, tmp_path)
    assert "-s" not in cmd, cmd


def _fake_runner(returncode, bundle_names):
    """Return a runner that simulates Synthea: writes bundles into <mount>/fhir."""
    def runner(cmd, **kwargs):
        out = None
        for i, part in enumerate(cmd):
            if part == "-v" and i + 1 < len(cmd):
                out = Path(cmd[i + 1].split(":", 1)[0])
        assert out is not None, f"no volume mount found in command: {cmd}"
        fhir = out / "fhir"
        fhir.mkdir(parents=True, exist_ok=True)
        if returncode == 0:
            for name in bundle_names:
                (fhir / name).write_text(json.dumps({"resourceType": "Bundle"}))
        return SimpleNamespace(returncode=returncode, stdout="", stderr="" if returncode == 0 else "synthea failed")
    return runner


def test_generate_cohort_returns_patient_bundles_only(tmp_path):
    runner = _fake_runner(0, [
        "Alice_Adams_1.json",
        "Bob_Baker_2.json",
        "hospitalInformation1.json",
        "practitionerInformation1.json",
    ])
    result = generate_cohort(2, tmp_path, runner=runner)
    names = sorted(p.name for p in result)
    assert names == ["Alice_Adams_1.json", "Bob_Baker_2.json"], names


def test_generate_cohort_raises_on_nonzero_exit(tmp_path):
    runner = _fake_runner(1, [])
    with pytest.raises(SyntheaError):
        generate_cohort(2, tmp_path, runner=runner)


def test_generate_cohort_raises_when_no_patient_bundles(tmp_path):
    runner = _fake_runner(0, ["hospitalInformation1.json"])  # rc=0 but no patient bundles
    with pytest.raises(SyntheaError):
        generate_cohort(2, tmp_path, runner=runner)
