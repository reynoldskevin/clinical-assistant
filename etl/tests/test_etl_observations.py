"""T05 acceptance tests (LOCKED) for the Synthea observations ETL.

Vital-signs → form_vitals (one row per patient+datetime), laboratory → the
procedure_order/report/result chain. Integration tests against a disposable
throwaway MySQL schema cloned from live `openemr`.
"""
import os
import pymysql
import pytest

from etl_patients import load_bundles as load_patients
from etl_observations import load_observations

MYSQL = dict(
    host=os.environ.get("ETL_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("ETL_DB_PORT", "8320")),
    user=os.environ.get("ETL_DB_USER", "root"),
    password=os.environ.get("ETL_DB_PASS", "root"),
)
SRC = os.environ.get("ETL_SRC_SCHEMA", "openemr")
TEST = "openemr_etl_test"
TABLES = ["patient_data", "uuid_registry", "form_vitals",
          "procedure_order", "procedure_report", "procedure_result"]

P = "aaaa1111-2222-3333-4444-555566667777"
T_VITALS = "2015-06-01T10:00:00+00:00"
T_LAB = "2015-06-02T09:00:00+00:00"


@pytest.fixture
def db():
    root = pymysql.connect(**MYSQL, autocommit=True)
    cur = root.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{TEST}`")
    cur.execute(f"CREATE DATABASE `{TEST}`")
    for t in TABLES:
        cur.execute(f"CREATE TABLE `{TEST}`.`{t}` LIKE `{SRC}`.`{t}`")
    root.close()
    conn = pymysql.connect(**MYSQL, database=TEST, autocommit=True)
    yield conn
    conn.close()
    root = pymysql.connect(**MYSQL, autocommit=True)
    root.cursor().execute(f"DROP DATABASE IF EXISTS `{TEST}`")
    root.close()


def _patient_entry():
    return {"resource": {
        "resourceType": "Patient", "id": P,
        "name": [{"use": "official", "family": "Obs", "given": ["Pat"]}],
        "gender": "female", "birthDate": "1975-01-01",
    }}


def _vital(uuid, loinc, value, unit, when=T_VITALS):
    return {"resource": {
        "resourceType": "Observation", "id": uuid, "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                  "code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc}], "text": loinc},
        "subject": {"reference": f"urn:uuid:{P}"},
        "effectiveDateTime": when,
        "valueQuantity": {"value": value, "unit": unit},
    }}


def _bp_panel(uuid, systolic, diastolic, when=T_VITALS):
    return {"resource": {
        "resourceType": "Observation", "id": uuid, "status": "final",
        "category": [{"coding": [{"code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}], "text": "Blood pressure"},
        "subject": {"reference": f"urn:uuid:{P}"},
        "effectiveDateTime": when,
        "component": [
            {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
             "valueQuantity": {"value": systolic, "unit": "mm[Hg]"}},
            {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
             "valueQuantity": {"value": diastolic, "unit": "mm[Hg]"}},
        ],
    }}


def _lab(uuid, loinc, display, value, unit, when=T_LAB):
    return {"resource": {
        "resourceType": "Observation", "id": uuid, "status": "final",
        "category": [{"coding": [{"code": "laboratory"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}], "text": display},
        "subject": {"reference": f"urn:uuid:{P}"},
        "effectiveDateTime": when,
        "valueQuantity": {"value": value, "unit": unit},
    }}


def _bundle(*obs):
    return {"resourceType": "Bundle", "type": "transaction",
            "entry": [_patient_entry()] + list(obs)}


def _full():
    return _bundle(
        _bp_panel("b0000000-0000-0000-0000-000000000001", 120, 80),
        _vital("v0000000-0000-0000-0000-000000000002", "29463-7", 70, "kg"),
        _vital("v0000000-0000-0000-0000-000000000003", "8867-4", 72, "/min"),
        _lab("l0000000-0000-0000-0000-000000000004", "2339-0", "Glucose", 95, "mg/dL"),
    )


def test_load_observations_vitals_aggregate_into_one_row(db):
    b = _full()
    assert load_patients([b], db) == 1
    counts = load_observations([b], db)
    assert counts["vitals"] == 1        # all vital-signs at one datetime -> one row

    cur = db.cursor()
    cur.execute("SELECT pid FROM patient_data")
    pid = cur.fetchone()[0]
    cur.execute("SELECT pid, bps, bpd, weight, pulse FROM form_vitals")
    rows = cur.fetchall()
    assert len(rows) == 1
    fpid, bps, bpd, weight, pulse = rows[0]
    assert fpid == pid
    assert bps == "120"                 # bps/bpd are varchar -> integer strings
    assert bpd == "80"
    assert float(weight) == 70.0
    assert float(pulse) == 72.0


def test_load_observations_lab_chain_linked_to_patient(db):
    b = _full()
    load_patients([b], db)
    counts = load_observations([b], db)
    assert counts["labs"] == 1

    cur = db.cursor()
    cur.execute("SELECT pid FROM patient_data")
    pid = cur.fetchone()[0]
    cur.execute("SELECT result_code, result, units FROM procedure_result")
    res = cur.fetchall()
    assert len(res) == 1
    code, result, units = res[0]
    assert "2339-0" in code
    assert "95" in result
    assert units == "mg/dL"
    # result links back to the patient through report -> order
    cur.execute(
        "SELECT po.patient_id FROM procedure_result pr "
        "JOIN procedure_report prpt ON prpt.procedure_report_id = pr.procedure_report_id "
        "JOIN procedure_order po ON po.procedure_order_id = prpt.procedure_order_id"
    )
    link = cur.fetchall()
    assert len(link) == 1 and link[0][0] == pid


def test_load_observations_idempotent(db):
    b = _full()
    load_patients([b], db)
    assert load_observations([b], db) == {"vitals": 1, "labs": 1}
    assert load_observations([b], db) == {"vitals": 0, "labs": 0}
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM form_vitals")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM procedure_result")
    assert cur.fetchone()[0] == 1


def test_load_observations_skips_when_patient_missing(db):
    b = _full()
    assert load_observations([b], db) == {"vitals": 0, "labs": 0}
    cur = db.cursor()
    for t in ("form_vitals", "procedure_result", "procedure_order", "procedure_report"):
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        assert cur.fetchone()[0] == 0
