-- Idempotent seed for the live-eval dedicated patient (pid 999).
--
-- The live eval sweep (`python -m eval --live`) reads the real OpenEMR chart
-- through the boundary. Most cases run against the Synthea cohort, but the
-- stale-active-medication case (uc6) needs a medication flagged ACTIVE whose
-- end_date is already in the past — a data-quality trap the agent must hedge on.
-- No Synthea patient reliably carries one, so this seeds a dedicated eval patient
-- (pid 999, well above the cohort's max id) with exactly that row. Idempotent:
-- re-running deletes and re-inserts, so it is safe to apply before every sweep.
-- Run:  docker exec <openemr> mysql ... openemr < sidecar/evals/seed_eval_patient.sql

DELETE FROM lists WHERE pid = 999;
DELETE FROM patient_data WHERE pid = 999;

INSERT INTO patient_data (pid, pubpid, fname, lname, DOB, sex, date)
VALUES (999, 'EVAL999', 'Eval', 'Patient', '1950-01-01', 'Male', NOW());

-- Stale-active anticoagulant: activity=1 (flagged active) but end_date is in the
-- past, so the medications tool reports status_conflict=true and a grounded
-- answer hedges ("listed as active, but its end date suggests it may be stale").
INSERT INTO lists (pid, type, title, activity, begdate, enddate, date, diagnosis)
VALUES (999, 'medication', 'Warfarin 5 mg daily', 1,
        '2023-01-01 00:00:00', '2024-06-01 00:00:00', NOW(), '');
