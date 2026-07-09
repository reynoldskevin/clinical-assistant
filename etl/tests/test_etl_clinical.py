"""T04 acceptance tests (LOCKED) for the Synthea clinical ETL.

Conditions/allergies → lists, MedicationRequest → prescriptions, Immunization →
immunizations. Integration tests against a disposable throwaway MySQL schema
cloned from live `openemr`. Uses T02's loader to set up the patient first.
"""
import os
import pymysql
import pytest

from etl_patients import load_bundles as load_patients
from etl_clinical import load_clinical

MYSQL = dict(
    host=os.environ.get("ETL_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("ETL_DB_PORT", "8320")),
    user=os.environ.get("ETL_DB_USER", "root"),
    password=os.environ.get("ETL_DB_PASS", "root"),
)
SRC = os.environ.get("ETL_SRC_SCHEMA", "openemr")
TEST = "openemr_etl_test"
TABLES = ["patient_data", "uuid_registry", "lists", "prescriptions", "immunizations"]

P = "aaaa1111-2222-3333-4444-555566667777"


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


def _patient_entry(uuid=P):
    return {"resource": {
        "resourceType": "Patient", "id": uuid,
        "name": [{"use": "official", "family": "Clinical", "given": ["Pat"]}],
        "gender": "male", "birthDate": "1970-01-01",
    }}


def _condition_entry(uuid="c0000000-0000-0000-0000-000000000001",
                     code="44054006", display="Type 2 diabetes mellitus"):
    return {"resource": {
        "resourceType": "Condition", "id": uuid,
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": code, "display": display}],
                 "text": display},
        "subject": {"reference": f"urn:uuid:{P}"},
        "onsetDateTime": "2010-03-15T00:00:00+00:00",
    }}


def _allergy_entry(uuid="a0000000-0000-0000-0000-000000000001",
                   code="91936005", display="Allergy to penicillin"):
    return {"resource": {
        "resourceType": "AllergyIntolerance", "id": uuid,
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": code, "display": display}],
                 "text": display},
        "patient": {"reference": f"urn:uuid:{P}"},
        "recordedDate": "2005-01-01T00:00:00+00:00",
    }}


def _medication_entry(uuid="d0000000-0000-0000-0000-000000000001",
                      rxnorm="860975", display="Metformin 500 MG Extended Release Oral Tablet"):
    return {"resource": {
        "resourceType": "MedicationRequest", "id": uuid, "status": "active", "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": rxnorm, "display": display}],
            "text": display},
        "subject": {"reference": f"urn:uuid:{P}"},
        "authoredOn": "2012-06-01T00:00:00+00:00",
    }}


def _immunization_entry(uuid="e0000000-0000-0000-0000-000000000001",
                        cvx="140", display="Influenza, seasonal, injectable"):
    return {"resource": {
        "resourceType": "Immunization", "id": uuid, "status": "completed",
        "vaccineCode": {"coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": cvx, "display": display}],
                        "text": display},
        "patient": {"reference": f"urn:uuid:{P}"},
        "occurrenceDateTime": "2015-09-15T00:00:00+00:00",
    }}


def _bundle(*clinical_entries):
    return {"resourceType": "Bundle", "type": "transaction",
            "entry": [_patient_entry()] + list(clinical_entries)}


def _full_bundle():
    return _bundle(_condition_entry(), _allergy_entry(), _medication_entry(), _immunization_entry())


def test_load_clinical_creates_all_types(db):
    b = _full_bundle()
    assert load_patients([b], db) == 1
    counts = load_clinical([b], db)
    assert counts == {"problems": 1, "allergies": 1, "medications": 1, "immunizations": 1}

    cur = db.cursor()
    cur.execute("SELECT pid FROM patient_data")
    pid = cur.fetchone()[0]

    # problem in lists
    cur.execute("SELECT type, title, diagnosis, activity FROM lists WHERE type='medical_problem'")
    prob = cur.fetchall()
    assert len(prob) == 1
    assert prob[0][1] == "Type 2 diabetes mellitus"
    assert "44054006" in prob[0][2] and prob[0][2].startswith("SNOMED")
    assert prob[0][3] == 1

    # allergy in lists
    cur.execute("SELECT COUNT(*) FROM lists WHERE type='allergy'")
    assert cur.fetchone()[0] == 1

    # medication in prescriptions
    cur.execute("SELECT patient_id, drug, rxnorm_drugcode, active FROM prescriptions")
    rx = cur.fetchall()
    assert len(rx) == 1
    assert rx[0][0] == pid
    assert rx[0][1] != ""
    assert rx[0][2] == "860975"
    assert rx[0][3] == 1

    # immunization
    cur.execute("SELECT patient_id, cvx_code FROM immunizations")
    imm = cur.fetchall()
    assert len(imm) == 1
    assert imm[0][0] == pid and imm[0][1] == "140"


def test_load_clinical_idempotent(db):
    b = _full_bundle()
    load_patients([b], db)
    assert load_clinical([b], db) == {"problems": 1, "allergies": 1, "medications": 1, "immunizations": 1}
    assert load_clinical([b], db) == {"problems": 0, "allergies": 0, "medications": 0, "immunizations": 0}
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM lists")
    assert cur.fetchone()[0] == 2
    cur.execute("SELECT COUNT(*) FROM prescriptions")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM immunizations")
    assert cur.fetchone()[0] == 1


def test_load_clinical_skips_when_patient_missing(db):
    b = _full_bundle()
    # patient NOT loaded
    assert load_clinical([b], db) == {"problems": 0, "allergies": 0, "medications": 0, "immunizations": 0}
    cur = db.cursor()
    for t in ("lists", "prescriptions", "immunizations"):
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        assert cur.fetchone()[0] == 0


def test_condition_code_and_med_code_mapping(db):
    b = _bundle(
        _condition_entry(code="38341003", display="Hypertension"),
        _medication_entry(rxnorm="311036", display="Amoxicillin 250 MG"),
    )
    load_patients([b], db)
    counts = load_clinical([b], db)
    assert counts["problems"] == 1 and counts["medications"] == 1
    cur = db.cursor()
    cur.execute("SELECT diagnosis FROM lists WHERE type='medical_problem'")
    assert "38341003" in cur.fetchone()[0]
    cur.execute("SELECT rxnorm_drugcode FROM prescriptions")
    assert cur.fetchone()[0] == "311036"
