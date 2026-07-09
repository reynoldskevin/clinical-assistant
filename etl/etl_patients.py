"""Synthea FHIR bundle -> OpenEMR patient_data ETL.

parse_patient() maps a Synthea-shaped FHIR transaction bundle's Patient
resource onto OpenEMR demographic fields. load_bundles() inserts those
patients into patient_data and registers their UUIDs, idempotently.
"""

_RACE_MAP = {
    "2106-3": "white",
    "2054-5": "black_or_afri_amer",
    "2028-9": "Asian",
    "1002-5": "amer_ind_or_alaska_native",
    "2076-8": "native_hawai_or_pac_island",
}

_ETHNICITY_MAP = {
    "2135-2": "hisp_or_latin",
    "2186-5": "not_hisp_or_latin",
}

_SEX_MAP = {
    "female": "Female",
    "male": "Male",
}

_RACE_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
_ETHNICITY_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"


def _find_patient(bundle):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            return resource
    return {}


def _omb_code(patient, url):
    for ext in patient.get("extension", []):
        if ext.get("url") != url:
            continue
        for sub in ext.get("extension", []):
            if sub.get("url") == "ombCategory":
                return sub.get("valueCoding", {}).get("code", "")
    return ""


def parse_patient(bundle):
    patient = _find_patient(bundle)

    names = patient.get("name") or [{}]
    name0 = names[0] if names else {}
    given = name0.get("given") or [""]
    fname = given[0] if given else ""
    lname = name0.get("family", "")

    addresses = patient.get("address") or [{}]
    addr0 = addresses[0] if addresses else {}
    lines = addr0.get("line") or [""]
    street = lines[0] if lines else ""

    phone_home = ""
    for tel in patient.get("telecom", []):
        if tel.get("system") == "phone":
            phone_home = tel.get("value", "")
            break

    gender = patient.get("gender", "")
    sex = _SEX_MAP.get(gender, "UNK") if gender else "UNK"

    race_code = _omb_code(patient, _RACE_URL)
    eth_code = _omb_code(patient, _ETHNICITY_URL)

    return {
        "uuid": patient.get("id", ""),
        "fname": fname,
        "lname": lname,
        "DOB": patient.get("birthDate", ""),
        "sex": sex,
        "race": _RACE_MAP.get(race_code, ""),
        "ethnicity": _ETHNICITY_MAP.get(eth_code, ""),
        "street": street,
        "city": addr0.get("city", ""),
        "state": addr0.get("state", ""),
        "postal_code": addr0.get("postalCode", ""),
        "phone_home": phone_home,
    }


_DEMOGRAPHIC_COLUMNS = (
    "fname", "lname", "DOB", "sex", "race", "ethnicity",
    "street", "city", "state", "postal_code", "phone_home",
)


def load_bundles(bundles, conn):
    inserted = 0
    cur = conn.cursor()
    for bundle in bundles:
        rec = parse_patient(bundle)
        uuid_str = rec["uuid"]

        cur.execute(
            "SELECT 1 FROM patient_data WHERE uuid = UNHEX(REPLACE(%s, '-', '')) LIMIT 1",
            (uuid_str,),
        )
        if cur.fetchone() is not None:
            continue

        cur.execute("SELECT COALESCE(MAX(pid), 0) + 1 FROM patient_data")
        pid = cur.fetchone()[0]

        columns = ["pid", "uuid"]
        placeholders = ["%s", "UNHEX(REPLACE(%s, '-', ''))"]
        values = [pid, uuid_str]
        for col in _DEMOGRAPHIC_COLUMNS:
            val = rec[col]
            if val != "":
                columns.append(col)
                placeholders.append("%s")
                values.append(val)

        sql = "INSERT INTO patient_data ({}) VALUES ({})".format(
            ", ".join("`{}`".format(c) for c in columns),
            ", ".join(placeholders),
        )
        cur.execute(sql, values)

        cur.execute(
            "INSERT INTO uuid_registry (uuid, table_name, table_id, created) "
            "VALUES (UNHEX(REPLACE(%s, '-', '')), 'patient_data', %s, NOW())",
            (uuid_str, pid),
        )
        inserted += 1

    return inserted
