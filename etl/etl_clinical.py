"""Synthea FHIR bundle -> OpenEMR clinical ETL.

load_clinical() resolves each bundle's Patient to an OpenEMR pid, then loads the
bundle's clinical resources, each idempotently by its own FHIR resource UUID:

  * Condition          -> lists         (type='medical_problem')
  * AllergyIntolerance -> lists         (type='allergy')
  * MedicationRequest  -> prescriptions
  * Immunization       -> immunizations
"""

from datetime import datetime

_SNOMED_SYSTEM = "http://snomed.info/sct"
_RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
_CVX_SYSTEM = "http://hl7.org/fhir/sid/cvx"


def _find_patient_uuid(bundle):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            return resource.get("id", "")
    return ""


def _iter_resources(bundle, resource_type):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == resource_type:
            yield resource


def _parse_datetime(value):
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_date(value):
    dt = _parse_datetime(value)
    if dt is None:
        return None
    return dt[:10]


def _coding_code(concept, system):
    for coding in (concept or {}).get("coding", []):
        if coding.get("system") == system:
            return coding.get("code", "")
    return ""


def _exists(cur, table, uuid):
    cur.execute(
        "SELECT 1 FROM {} WHERE uuid = UNHEX(REPLACE(%s, '-', '')) LIMIT 1".format(table),
        (uuid,),
    )
    return cur.fetchone() is not None


def load_clinical(bundles, conn):
    counts = {"problems": 0, "allergies": 0, "medications": 0, "immunizations": 0}
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

        for cond in _iter_resources(bundle, "Condition"):
            uuid = cond.get("id", "")
            if _exists(cur, "lists", uuid):
                continue
            code = cond.get("code") or {}
            diagnosis = "SNOMED-CT:" + _coding_code(code, _SNOMED_SYSTEM)
            date = _parse_datetime(cond.get("onsetDateTime", ""))
            cur.execute(
                "INSERT INTO lists (pid, type, title, diagnosis, begdate, date, activity, uuid) "
                "VALUES (%s, 'medical_problem', %s, %s, %s, %s, 1, UNHEX(REPLACE(%s, '-', '')))",
                (pid, code.get("text", ""), diagnosis, date, date, uuid),
            )
            counts["problems"] += 1

        for allergy in _iter_resources(bundle, "AllergyIntolerance"):
            uuid = allergy.get("id", "")
            if _exists(cur, "lists", uuid):
                continue
            code = allergy.get("code") or {}
            diagnosis = "SNOMED-CT:" + _coding_code(code, _SNOMED_SYSTEM)
            date = _parse_datetime(allergy.get("recordedDate", ""))
            cur.execute(
                "INSERT INTO lists (pid, type, title, diagnosis, begdate, date, activity, uuid) "
                "VALUES (%s, 'allergy', %s, %s, %s, %s, 1, UNHEX(REPLACE(%s, '-', '')))",
                (pid, code.get("text", ""), diagnosis, date, date, uuid),
            )
            counts["allergies"] += 1

        for med in _iter_resources(bundle, "MedicationRequest"):
            uuid = med.get("id", "")
            if _exists(cur, "prescriptions", uuid):
                continue
            concept = med.get("medicationCodeableConcept") or {}
            rxnorm = _coding_code(concept, _RXNORM_SYSTEM)
            date = _parse_date(med.get("authoredOn", ""))
            cur.execute(
                "INSERT INTO prescriptions "
                "(patient_id, drug, rxnorm_drugcode, active, provider_id, "
                "date_added, start_date, txDate, usage_category_title, request_intent_title, uuid) "
                "VALUES (%s, %s, %s, 1, 0, %s, %s, %s, '', '', UNHEX(REPLACE(%s, '-', '')))",
                (pid, concept.get("text", ""), rxnorm, date, date, date, uuid),
            )
            counts["medications"] += 1

        for imm in _iter_resources(bundle, "Immunization"):
            uuid = imm.get("id", "")
            if _exists(cur, "immunizations", uuid):
                continue
            vaccine = imm.get("vaccineCode") or {}
            cvx = _coding_code(vaccine, _CVX_SYSTEM)
            date = _parse_datetime(imm.get("occurrenceDateTime", ""))
            cur.execute(
                "INSERT INTO immunizations "
                "(patient_id, cvx_code, administered_date, note, created_by, update_date, uuid) "
                "VALUES (%s, %s, %s, %s, 0, NOW(), UNHEX(REPLACE(%s, '-', '')))",
                (pid, cvx, date, vaccine.get("text", ""), uuid),
            )
            counts["immunizations"] += 1

    return counts
