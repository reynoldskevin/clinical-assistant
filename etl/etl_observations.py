"""Synthea FHIR bundle -> OpenEMR observations ETL.

load_observations() resolves each bundle's Patient to an OpenEMR pid, then
classifies each Observation by its category coding:

  * vital-signs -> form_vitals   (one row per patient+datetime, grouped)
  * laboratory  -> procedure_order -> procedure_report -> procedure_result

Both paths are idempotent: vitals dedup by (pid, date); labs dedup by
(pid, result_code, date) via the result -> report -> order join.
"""

from datetime import datetime

_LOINC_SYSTEM = "http://loinc.org"

# LOINC code -> form_vitals column for the "own code" and component mappings.
_VITAL_COLUMNS = {
    "8480-6": "bps",
    "8462-4": "bpd",
    "29463-7": "weight",
    "8867-4": "pulse",
    "8302-2": "height",
    "8310-5": "temperature",
    "9279-1": "respiration",
    "2708-6": "oxygen_saturation",
    "59408-5": "oxygen_saturation",
    "39156-5": "BMI",
}

# Columns stored as varchar integer strings rather than decimals.
_VARCHAR_INT_COLUMNS = {"bps", "bpd"}


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


def _loinc_code(concept):
    for coding in (concept or {}).get("coding", []):
        if coding.get("system") == _LOINC_SYSTEM:
            return coding.get("code", "")
    codings = (concept or {}).get("coding", [])
    return codings[0].get("code", "") if codings else ""


def _category_codes(obs):
    codes = []
    for category in obs.get("category", []):
        for coding in category.get("coding", []):
            code = coding.get("code")
            if code:
                codes.append(code)
    return codes


def _column_value(column, value):
    if value is None:
        return None
    if column in _VARCHAR_INT_COLUMNS:
        return str(int(value))
    return value


def _load_vitals(bundle, pid, cur):
    inserted = 0
    # Group vital-signs observations by their effectiveDateTime.
    groups = {}
    for obs in _iter_resources(bundle, "Observation"):
        if "vital-signs" not in _category_codes(obs):
            continue
        date = _parse_datetime(obs.get("effectiveDateTime", ""))
        groups.setdefault(date, []).append(obs)

    for date, observations in groups.items():
        cur.execute(
            "SELECT 1 FROM form_vitals WHERE pid = %s AND date = %s LIMIT 1",
            (pid, date),
        )
        if cur.fetchone() is not None:
            continue

        columns = {}
        for obs in observations:
            components = obs.get("component") or []
            if components:
                for comp in components:
                    loinc = _loinc_code(comp.get("code") or {})
                    column = _VITAL_COLUMNS.get(loinc)
                    if not column:
                        continue
                    value = (comp.get("valueQuantity") or {}).get("value")
                    columns[column] = _column_value(column, value)
            else:
                loinc = _loinc_code(obs.get("code") or {})
                column = _VITAL_COLUMNS.get(loinc)
                if not column:
                    continue
                value = (obs.get("valueQuantity") or {}).get("value")
                columns[column] = _column_value(column, value)

        col_names = ["pid", "date"] + list(columns.keys())
        placeholders = ", ".join(["%s"] * len(col_names))
        cur.execute(
            "INSERT INTO form_vitals ({}) VALUES ({})".format(
                ", ".join(col_names), placeholders
            ),
            [pid, date] + list(columns.values()),
        )
        inserted += 1

    return inserted


def _lab_exists(cur, pid, result_code, date):
    cur.execute(
        "SELECT 1 FROM procedure_result pr "
        "JOIN procedure_report prpt "
        "ON prpt.procedure_report_id = pr.procedure_report_id "
        "JOIN procedure_order po "
        "ON po.procedure_order_id = prpt.procedure_order_id "
        "WHERE po.patient_id = %s AND pr.result_code = %s AND pr.date = %s LIMIT 1",
        (pid, result_code, date),
    )
    return cur.fetchone() is not None


def _load_labs(bundle, pid, cur):
    inserted = 0
    for obs in _iter_resources(bundle, "Observation"):
        if "laboratory" not in _category_codes(obs):
            continue

        code = obs.get("code") or {}
        result_code = _loinc_code(code)
        date = _parse_datetime(obs.get("effectiveDateTime", ""))

        if _lab_exists(cur, pid, result_code, date):
            continue

        quantity = obs.get("valueQuantity") or {}
        codings = code.get("coding", [])
        display = codings[0].get("display", "") if codings else ""
        result_text = display or code.get("text", "")
        value = quantity.get("value")

        cur.execute(
            "INSERT INTO procedure_order (patient_id, date_ordered, provider_id) "
            "VALUES (%s, %s, 0)",
            (pid, date),
        )
        order_id = cur.lastrowid

        cur.execute(
            "INSERT INTO procedure_report "
            "(procedure_order_id, date_collected, date_report, report_status) "
            "VALUES (%s, %s, %s, 'final')",
            (order_id, date, date),
        )
        report_id = cur.lastrowid

        cur.execute(
            "INSERT INTO procedure_result "
            "(procedure_report_id, result_code, result_text, result, units, date) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                report_id,
                result_code,
                result_text,
                None if value is None else str(value),
                quantity.get("unit", ""),
                date,
            ),
        )
        inserted += 1

    return inserted


def load_observations(bundles, conn):
    counts = {"vitals": 0, "labs": 0}
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

        counts["vitals"] += _load_vitals(bundle, pid, cur)
        counts["labs"] += _load_labs(bundle, pid, cur)

    return counts
