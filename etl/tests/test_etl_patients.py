"""T02 acceptance tests (LOCKED contract) for the Synthea → patient_data ETL.

Integration tests: they run against a disposable throwaway MySQL schema
(`openemr_etl_test`) whose tables are cloned from the live `openemr` DB, so the
inserts exercise the real column layout. Requires the dev MySQL to be reachable
(development-easy on 127.0.0.1:8320). These are NOT marked `integration` — they
are T02's core contract and must run in the loop; the `integration` mark is
reserved for the real Synthea docker run / live load.
"""
import os
import pymysql
import pytest

from etl_patients import parse_patient, load_bundles

MYSQL = dict(
    host=os.environ.get("ETL_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("ETL_DB_PORT", "8320")),
    user=os.environ.get("ETL_DB_USER", "root"),
    password=os.environ.get("ETL_DB_PASS", "root"),
)
SRC_SCHEMA = os.environ.get("ETL_SRC_SCHEMA", "openemr")
TEST_SCHEMA = "openemr_etl_test"


@pytest.fixture
def db():
    """Fresh throwaway schema with patient_data + uuid_registry cloned from openemr."""
    root = pymysql.connect(**MYSQL, autocommit=True)
    cur = root.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{TEST_SCHEMA}`")
    cur.execute(f"CREATE DATABASE `{TEST_SCHEMA}`")
    cur.execute(f"CREATE TABLE `{TEST_SCHEMA}`.patient_data LIKE `{SRC_SCHEMA}`.patient_data")
    cur.execute(f"CREATE TABLE `{TEST_SCHEMA}`.uuid_registry LIKE `{SRC_SCHEMA}`.uuid_registry")
    root.close()
    conn = pymysql.connect(**MYSQL, database=TEST_SCHEMA, autocommit=True)
    yield conn
    conn.close()
    root = pymysql.connect(**MYSQL, autocommit=True)
    root.cursor().execute(f"DROP DATABASE IF EXISTS `{TEST_SCHEMA}`")
    root.close()


def _patient_bundle(pid_uuid="11111111-1111-1111-1111-111111111111",
                    family="Adams", given="Alice", gender="female",
                    birth="1980-05-14", race_code="2106-3", race_text="White",
                    eth_code="2186-5", eth_text="Not Hispanic or Latino",
                    line="123 Oak St", city="Denver", state="CO", postal="80202",
                    phone="555-123-4567"):
    """A realistic Synthea-shaped transaction bundle with one Patient resource
    (plus a non-Patient resource that parsing must ignore)."""
    return {
        "resourceType": "Bundle", "type": "transaction",
        "entry": [
            {"resource": {"resourceType": "Encounter", "id": "enc-should-be-ignored"}},
            {"resource": {
                "resourceType": "Patient", "id": pid_uuid,
                "extension": [
                    {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
                     "extension": [
                         {"url": "ombCategory", "valueCoding": {
                             "system": "urn:oid:2.16.840.1.113883.6.238", "code": race_code, "display": race_text}},
                         {"url": "text", "valueString": race_text}]},
                    {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                     "extension": [
                         {"url": "ombCategory", "valueCoding": {"code": eth_code, "display": eth_text}},
                         {"url": "text", "valueString": eth_text}]},
                ],
                "name": [{"use": "official", "family": family, "given": [given]}],
                "gender": gender, "birthDate": birth,
                "address": [{"line": [line], "city": city, "state": state, "postalCode": postal}],
                "telecom": [{"system": "phone", "value": phone, "use": "home"}],
            }},
        ],
    }


# ---- parsing -------------------------------------------------------------

def test_parse_maps_core_demographic_fields():
    rec = parse_patient(_patient_bundle())
    assert rec["uuid"] == "11111111-1111-1111-1111-111111111111"
    assert rec["fname"] == "Alice"
    assert rec["lname"] == "Adams"
    assert rec["DOB"] == "1980-05-14"
    assert rec["sex"] == "Female"                 # FHIR female -> list_options 'sex'
    assert rec["race"] == "white"                 # OMB 2106-3 -> list_options 'race'
    assert rec["ethnicity"] == "not_hisp_or_latin"  # OMB 2186-5 -> list_options 'ethnicity'
    assert rec["street"] == "123 Oak St"
    assert rec["city"] == "Denver"
    assert rec["state"] == "CO"
    assert rec["postal_code"] == "80202"
    assert rec["phone_home"] == "555-123-4567"


def test_parse_maps_a_second_race_code():
    rec = parse_patient(_patient_bundle(race_code="2054-5", race_text="Black or African American"))
    assert rec["race"] == "black_or_afri_amer"


def test_parse_unmapped_race_is_blank_not_fabricated():
    rec = parse_patient(_patient_bundle(race_code="9999-9", race_text="Nonexistent"))
    assert rec["race"] == ""   # unknown code -> blank, never invented


def test_parse_male_gender():
    rec = parse_patient(_patient_bundle(gender="male"))
    assert rec["sex"] == "Male"


# ---- loading -------------------------------------------------------------

def test_load_inserts_patient_and_registers_uuid(db):
    n = load_bundles([_patient_bundle()], db)
    assert n == 1
    cur = db.cursor()
    cur.execute("SELECT pid, fname, lname, sex, DATE_FORMAT(DOB,'%Y-%m-%d'), HEX(uuid) FROM patient_data")
    rows = cur.fetchall()
    assert len(rows) == 1
    pid, fname, lname, sex, dob, uhex = rows[0]
    assert (fname, lname, sex, dob) == ("Alice", "Adams", "Female", "1980-05-14")
    assert uhex.lower() == "11111111111111111111111111111111"
    cur.execute("SELECT table_name, table_id, HEX(uuid) FROM uuid_registry")
    reg = cur.fetchall()
    assert len(reg) == 1
    assert reg[0][0] == "patient_data"
    assert int(reg[0][1]) == pid   # uuid_registry.table_id is varchar(255) -> compare coerced
    assert reg[0][2].lower() == "11111111111111111111111111111111"


def test_load_is_idempotent(db):
    b = _patient_bundle()
    assert load_bundles([b], db) == 1
    assert load_bundles([b], db) == 0          # second load inserts nothing
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM patient_data")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM uuid_registry")
    assert cur.fetchone()[0] == 1


def test_load_count_matches_input_and_pids_unique(db):
    bundles = [
        _patient_bundle(pid_uuid="aaaaaaaa-0000-0000-0000-000000000001", family="One"),
        _patient_bundle(pid_uuid="bbbbbbbb-0000-0000-0000-000000000002", family="Two"),
    ]
    assert load_bundles(bundles, db) == 2
    cur = db.cursor()
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT pid) FROM patient_data")
    total, distinct_pids = cur.fetchone()
    assert total == 2 and distinct_pids == 2
