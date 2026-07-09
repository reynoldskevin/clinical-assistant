"""T03 acceptance tests (LOCKED) for the Synthea → form_encounter/forms ETL.

Integration tests against a disposable throwaway MySQL schema (cloned from live
`openemr`). Uses T02's etl_patients.load_bundles to set up the patient first.
"""
import os
import pymysql
import pytest

from etl_patients import load_bundles as load_patients
from etl_encounters import load_encounters

MYSQL = dict(
    host=os.environ.get("ETL_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("ETL_DB_PORT", "8320")),
    user=os.environ.get("ETL_DB_USER", "root"),
    password=os.environ.get("ETL_DB_PASS", "root"),
)
SRC = os.environ.get("ETL_SRC_SCHEMA", "openemr")
TEST = "openemr_etl_test"
TABLES = ["patient_data", "uuid_registry", "form_encounter", "forms"]


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


def _patient_entry(uuid):
    return {"resource": {
        "resourceType": "Patient", "id": uuid,
        "name": [{"use": "official", "family": "Encounter", "given": ["Pat"]}],
        "gender": "female", "birthDate": "1980-05-14",
    }}


def _encounter_entry(uuid, patient_uuid, start, reason):
    return {"resource": {
        "resourceType": "Encounter", "id": uuid, "status": "finished",
        "type": [{"text": reason}],
        "subject": {"reference": f"urn:uuid:{patient_uuid}"},
        "period": {"start": f"{start}T10:00:00+00:00", "end": f"{start}T10:30:00+00:00"},
    }}


def _bundle(patient_uuid, encounters):
    entries = [_patient_entry(patient_uuid)]
    for enc_uuid, start, reason in encounters:
        entries.append(_encounter_entry(enc_uuid, patient_uuid, start, reason))
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


P = "aaaa1111-2222-3333-4444-555566667777"


def test_load_encounters_creates_form_encounter_and_forms(db):
    b = _bundle(P, [
        ("e1111111-0000-0000-0000-000000000001", "2015-06-01", "Check up"),
        ("e2222222-0000-0000-0000-000000000002", "2016-02-10", "Follow up"),
    ])
    assert load_patients([b], db) == 1
    assert load_encounters([b], db) == 2

    cur = db.cursor()
    cur.execute("SELECT pid FROM patient_data")
    pid = cur.fetchone()[0]

    cur.execute("SELECT encounter, DATE_FORMAT(date,'%Y-%m-%d'), reason, pid FROM form_encounter ORDER BY date")
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "2015-06-01" and rows[0][2] == "Check up" and rows[0][3] == pid
    assert rows[1][1] == "2016-02-10" and rows[1][2] == "Follow up"

    # every encounter has a matching forms registry row linking back to it
    cur.execute(
        "SELECT fe.id, f.form_id, f.formdir, f.pid, f.encounter, f.deleted "
        "FROM form_encounter fe JOIN forms f "
        "ON f.form_id = fe.id AND f.pid = fe.pid AND f.encounter = fe.encounter"
    )
    fr = cur.fetchall()
    assert len(fr) == 2
    for fe_id, form_id, formdir, fpid, fenc, deleted in fr:
        assert form_id == fe_id
        assert formdir == "newpatient"
        assert fpid == pid
        assert deleted == 0


def test_load_encounters_idempotent(db):
    b = _bundle(P, [("e1111111-0000-0000-0000-000000000001", "2015-06-01", "Check up")])
    load_patients([b], db)
    assert load_encounters([b], db) == 1
    assert load_encounters([b], db) == 0
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM form_encounter")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM forms")
    assert cur.fetchone()[0] == 1


def test_load_encounters_skips_when_patient_missing(db):
    b = _bundle(P, [("e1111111-0000-0000-0000-000000000001", "2015-06-01", "Check up")])
    # patient NOT loaded first
    assert load_encounters([b], db) == 0
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM form_encounter")
    assert cur.fetchone()[0] == 0


def test_encounter_numbers_are_unique(db):
    b = _bundle(P, [
        ("e1111111-0000-0000-0000-000000000001", "2015-06-01", "a"),
        ("e2222222-0000-0000-0000-000000000002", "2016-01-01", "b"),
    ])
    load_patients([b], db)
    load_encounters([b], db)
    cur = db.cursor()
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT encounter) FROM form_encounter")
    total, distinct = cur.fetchone()
    assert total == 2 and distinct == 2
