"""T05b acceptance tests (LOCKED) for encounter-form registration of vitals/labs.

register_forms links already-loaded form_vitals and procedure_order rows to their
encounters via the `forms` registry, so the OpenEMR encounter UI renders them.
Integration tests against a disposable throwaway MySQL schema cloned from openemr.
"""
import os
import pymysql
import pytest

from etl_patients import load_bundles as load_patients
from etl_encounters import load_encounters
from etl_observations import load_observations
from etl_forms import register_forms

MYSQL = dict(
    host=os.environ.get("ETL_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("ETL_DB_PORT", "8320")),
    user=os.environ.get("ETL_DB_USER", "root"),
    password=os.environ.get("ETL_DB_PASS", "root"),
)
SRC = os.environ.get("ETL_SRC_SCHEMA", "openemr")
TEST = "openemr_etl_test"
TABLES = ["patient_data", "uuid_registry", "form_encounter", "forms",
          "form_vitals", "procedure_order", "procedure_report", "procedure_result"]

P = "aaaa1111-2222-3333-4444-555566667777"
ENC = "bbbb2222-3333-4444-5555-666677778888"
WHEN = "2015-06-01T10:00:00+00:00"


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


def _bundle():
    enc_ref = {"reference": f"urn:uuid:{ENC}"}
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        {"resource": {"resourceType": "Patient", "id": P,
                      "name": [{"family": "Forms", "given": ["Pat"]}],
                      "gender": "male", "birthDate": "1970-01-01"}},
        {"resource": {"resourceType": "Encounter", "id": ENC, "status": "finished",
                      "type": [{"text": "Office visit"}],
                      "subject": {"reference": f"urn:uuid:{P}"},
                      "period": {"start": WHEN}}},
        {"resource": {"resourceType": "Observation", "id": "obs-bp-1", "status": "final",
                      "category": [{"coding": [{"code": "vital-signs"}]}],
                      "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
                      "subject": {"reference": f"urn:uuid:{P}"}, "encounter": enc_ref,
                      "effectiveDateTime": WHEN,
                      "component": [
                          {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                           "valueQuantity": {"value": 120, "unit": "mm[Hg]"}},
                          {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                           "valueQuantity": {"value": 80, "unit": "mm[Hg]"}},
                      ]}},
        {"resource": {"resourceType": "Observation", "id": "obs-wt-1", "status": "final",
                      "category": [{"coding": [{"code": "vital-signs"}]}],
                      "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7"}]},
                      "subject": {"reference": f"urn:uuid:{P}"}, "encounter": enc_ref,
                      "effectiveDateTime": WHEN,
                      "valueQuantity": {"value": 70, "unit": "kg"}}},
        {"resource": {"resourceType": "Observation", "id": "obs-lab-1", "status": "final",
                      "category": [{"coding": [{"code": "laboratory"}]}],
                      "code": {"coding": [{"system": "http://loinc.org", "code": "2339-0", "display": "Glucose"}],
                               "text": "Glucose"},
                      "subject": {"reference": f"urn:uuid:{P}"}, "encounter": enc_ref,
                      "effectiveDateTime": WHEN,
                      "valueQuantity": {"value": 95, "unit": "mg/dL"}}},
    ]}


def _setup(db):
    b = _bundle()
    load_patients([b], db)
    load_encounters([b], db)
    load_observations([b], db)
    return b


def _encounter_number(db):
    cur = db.cursor()
    cur.execute("SELECT encounter FROM form_encounter")
    return cur.fetchone()[0]


def test_register_forms_links_vitals_and_labs(db):
    b = _setup(db)
    counts = register_forms([b], db)
    assert counts == {"vitals": 1, "labs": 1}

    cur = db.cursor()
    cur.execute("SELECT pid FROM patient_data")
    pid = cur.fetchone()[0]
    enc = _encounter_number(db)

    # vitals form registered and linked to the encounter
    cur.execute("SELECT id FROM form_vitals")
    fv_id = cur.fetchone()[0]
    cur.execute("SELECT form_id, encounter, pid, deleted, form_name FROM forms WHERE formdir='vitals'")
    vrows = cur.fetchall()
    assert len(vrows) == 1
    assert vrows[0][0] == fv_id
    assert vrows[0][1] == enc
    assert vrows[0][2] == pid
    assert vrows[0][3] == 0
    assert vrows[0][4] == "Vitals"

    # lab: procedure_order linked to encounter + a procedure_order form row
    cur.execute("SELECT procedure_order_id, encounter_id FROM procedure_order")
    po_id, enc_id = cur.fetchone()
    assert enc_id == enc
    cur.execute("SELECT form_id, encounter, form_name FROM forms WHERE formdir='procedure_order'")
    lrows = cur.fetchall()
    assert len(lrows) == 1
    assert lrows[0][0] == po_id
    assert lrows[0][1] == enc
    assert lrows[0][2] == "Procedure Order"


def test_register_forms_idempotent(db):
    b = _setup(db)
    assert register_forms([b], db) == {"vitals": 1, "labs": 1}
    assert register_forms([b], db) == {"vitals": 0, "labs": 0}
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM forms WHERE formdir='vitals'")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM forms WHERE formdir='procedure_order'")
    assert cur.fetchone()[0] == 1


def test_register_forms_skips_when_encounter_unresolved(db):
    # load patient + observations but NOT the encounter -> encounter ref can't resolve
    b = _bundle()
    load_patients([b], db)
    load_observations([b], db)   # note: no load_encounters
    counts = register_forms([b], db)
    assert counts == {"vitals": 0, "labs": 0}
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM forms WHERE formdir IN ('vitals','procedure_order')")
    assert cur.fetchone()[0] == 0
