"""Synthea FHIR bundle -> OpenEMR form_encounter/forms ETL.

load_encounters() resolves each bundle's Patient to an OpenEMR pid, then
inserts each Encounter resource into form_encounter (with a matching forms
registry row), idempotently by the Encounter's own UUID.
"""

from datetime import datetime


def _find_patient_uuid(bundle):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            return resource.get("id", "")
    return ""


def _iter_encounters(bundle):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Encounter":
            yield resource


def _parse_datetime(value):
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def load_encounters(bundles, conn):
    inserted = 0
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

        for enc in _iter_encounters(bundle):
            enc_uuid = enc.get("id", "")

            cur.execute(
                "SELECT 1 FROM form_encounter WHERE uuid = UNHEX(REPLACE(%s, '-', '')) LIMIT 1",
                (enc_uuid,),
            )
            if cur.fetchone() is not None:
                continue

            cur.execute("SELECT COALESCE(MAX(encounter), 0) + 1 FROM form_encounter")
            encounter = cur.fetchone()[0]

            date = _parse_datetime((enc.get("period") or {}).get("start", ""))

            types = enc.get("type") or []
            reason = types[0].get("text", "") if types else ""

            cur.execute(
                "INSERT INTO form_encounter (pid, encounter, date, reason, provider_id, uuid) "
                "VALUES (%s, %s, %s, %s, 0, UNHEX(REPLACE(%s, '-', '')))",
                (pid, encounter, date, reason, enc_uuid),
            )
            form_id = cur.lastrowid

            cur.execute(
                "INSERT INTO forms (pid, encounter, date, form_name, formdir, form_id, deleted) "
                "VALUES (%s, %s, %s, %s, %s, %s, 0)",
                (pid, encounter, date, "New Patient Encounter", "newpatient", form_id),
            )

            inserted += 1

    return inserted
