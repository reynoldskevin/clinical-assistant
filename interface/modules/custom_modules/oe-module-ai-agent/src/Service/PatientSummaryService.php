<?php

/**
 * PatientSummaryService — assembles a "minimum necessary" clinical summary
 * for a single patient from the OpenEMR schema via an injected PDO.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Service;

final class PatientSummaryService implements ChartReadProviderInterface
{
    public function __construct(
        private readonly \PDO $db,
        private readonly int $recentLimit = 5,
    ) {
    }

    /**
     * @return array{
     *     demographics: array<string, mixed>,
     *     problems: list<array<string, mixed>>,
     *     medications: list<array<string, mixed>>,
     *     allergies: list<array<string, mixed>>,
     *     recent_encounters: list<array<string, mixed>>,
     *     recent_vitals: list<array<string, mixed>>,
     *     recent_labs: list<array<string, mixed>>,
     * }
     */
    public function getSummary(int $pid): array
    {
        return [
            'demographics' => $this->demographics($pid),
            'problems' => $this->problems($pid),
            'medications' => $this->medications($pid),
            'allergies' => $this->allergies($pid),
            'recent_encounters' => $this->recentEncounters($pid),
            'recent_vitals' => $this->recentVitals($pid),
            'recent_labs' => $this->recentLabs($pid),
        ];
    }

    /**
     * @return list<array<string, mixed>>
     */
    public function listEncounters(int $pid): array
    {
        return $this->fetchList(
            'SELECT encounter, date, reason, provider_id FROM form_encounter '
            . 'WHERE pid = ? ORDER BY date DESC',
            $pid
        );
    }

    /**
     * The pid scope is the security boundary: an encounter id belonging to a
     * different patient yields no row (returns []), so a model-chosen id can
     * never cross charts.
     *
     * @return array<string, mixed>
     */
    public function getEncounter(int $pid, int $encounterId): array
    {
        $stmt = $this->db->prepare(
            'SELECT encounter, date, reason, provider_id, facility, encounter_type_description '
            . 'FROM form_encounter WHERE pid = ? AND encounter = ?'
        );
        $stmt->bindValue(1, $pid, \PDO::PARAM_INT);
        $stmt->bindValue(2, $encounterId, \PDO::PARAM_INT);
        $stmt->execute();

        $row = $stmt->fetch(\PDO::FETCH_ASSOC);

        return is_array($row) ? $row : [];
    }

    /**
     * The dedicated, complete lab/diagnostic results read — distinct from the
     * summary's capped recent_labs. Pid-scoped via the procedure_order join, so
     * only this patient's results are returned, most-recent-first.
     *
     * @return list<array<string, mixed>>
     */
    public function getResults(int $pid): array
    {
        return $this->fetchList(
            'SELECT pr.result_code, pr.result_text, pr.result, pr.units, pr.`range`, '
            . 'pr.abnormal, pr.date, pr.result_status FROM procedure_result pr '
            . 'JOIN procedure_report prpt ON prpt.procedure_report_id = pr.procedure_report_id '
            . 'JOIN procedure_order po ON po.procedure_order_id = prpt.procedure_order_id '
            . 'WHERE po.patient_id = ? '
            . 'ORDER BY pr.date DESC',
            $pid
        );
    }

    /**
     * The dedicated medications read — unions `prescriptions` and
     * medication-type `lists` rows for this patient only, most-recent-first by
     * start date. Each row carries a "stale-active" data-quality flag
     * (status_conflict): true iff the row is flagged active yet its own end_date
     * has already passed (per ARCHITECTURE.md §2.5). When $activeOnly is true,
     * only rows whose active flag is set are returned — but flagged stale-active
     * rows are still active, so they are kept (and flagged), not dropped.
     *
     * @return list<array<string, mixed>>
     */
    public function getMedications(int $pid, bool $activeOnly): array
    {
        // stale-active = an active row whose end date is a real date already in the
        // past. A date column may be NULL, a zero date, or (from some imports) an
        // empty string; compare it to CURDATE() with a lower floor rather than using
        // a '' / '0000-00-00' literal or DATE(): those coerce '' to a date and MySQL
        // in strict mode (unlike MariaDB) errors "Incorrect DATE value: ''". NULL,
        // zero dates and '' all fall below the '1000-01-01' floor, so are never flagged.
        $staleConflict = static fn (string $active, string $end): string =>
            "({$active} = 1 AND {$end} > '1000-01-01' AND {$end} < CURDATE())";

        $prescriptions =
            'SELECT '
            . "CONCAT('prescription:', p.id) AS ref, "
            . 'p.drug AS drug, '
            . 'p.rxnorm_drugcode AS rxnorm, '
            . 'p.active AS active, '
            . 'p.start_date AS start_date, '
            . 'p.end_date AS end_date, '
            . $staleConflict('p.active', 'p.end_date') . ' AS status_conflict '
            . 'FROM prescriptions p WHERE p.patient_id = ?'
            . ($activeOnly ? ' AND p.active = 1' : '');

        $listMeds =
            'SELECT '
            . "CONCAT('list:', l.id) AS ref, "
            . 'l.title AS drug, '
            . 'l.diagnosis AS rxnorm, '
            . 'l.activity AS active, '
            . 'l.begdate AS start_date, '
            . 'l.enddate AS end_date, '
            . $staleConflict('l.activity', 'l.enddate') . ' AS status_conflict '
            . "FROM lists l WHERE l.pid = ? AND l.type = 'medication'"
            . ($activeOnly ? ' AND l.activity = 1' : '');

        $sql = $prescriptions . ' UNION ALL ' . $listMeds . ' ORDER BY start_date DESC';

        $stmt = $this->db->prepare($sql);
        $stmt->bindValue(1, $pid, \PDO::PARAM_INT);
        $stmt->bindValue(2, $pid, \PDO::PARAM_INT);
        $stmt->execute();

        $rows = [];
        foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
            $row['active'] = (bool) $row['active'];
            $row['status_conflict'] = (bool) $row['status_conflict'];
            $rows[] = $row;
        }

        return $rows;
    }

    /**
     * Free-text search over the patient's note sources (`pnotes` + `form_soap`),
     * pid-scoped, returning snippet rows (never whole documents) most-recent-first
     * and capped by $limit. The query is matched with a BOUND `LIKE '%…%'` (never
     * interpolated) and each snippet is truncated to 300 chars in PHP after fetch
     * (minimum-necessary). An empty/whitespace query returns [] — no search.
     *
     * @return list<array{ref: string, source_type: string, date: mixed, snippet: string}>
     */
    public function searchChart(int $pid, string $query, int $limit): array
    {
        if (trim($query) === '') {
            return [];
        }

        // Clamp the row cap to a sane range before inlining it as an int LIMIT
        // (same pattern as recentEncounters — an int cast, not a bound param).
        $cap = max(0, min(50, $limit));
        if ($cap === 0) {
            return [];
        }

        $like = '%' . $query . '%';

        $notes =
            "SELECT CONCAT('pnote:', id) AS ref, 'note' AS source_type, date, "
            . 'COALESCE(NULLIF(body, \'\'), title) AS snippet '
            . 'FROM pnotes WHERE pid = ? AND (title LIKE ? OR body LIKE ?)';

        $soap =
            "SELECT CONCAT('soap:', id) AS ref, 'soap' AS source_type, date, "
            . "CONCAT_WS(' ', subjective, objective, assessment, plan) AS snippet "
            . 'FROM form_soap WHERE pid = ? '
            . 'AND (subjective LIKE ? OR objective LIKE ? OR assessment LIKE ? OR plan LIKE ?)';

        $sql = $notes . ' UNION ALL ' . $soap . ' ORDER BY date DESC LIMIT ' . $cap;

        $stmt = $this->db->prepare($sql);
        $stmt->bindValue(1, $pid, \PDO::PARAM_INT);
        $stmt->bindValue(2, $like, \PDO::PARAM_STR);
        $stmt->bindValue(3, $like, \PDO::PARAM_STR);
        $stmt->bindValue(4, $pid, \PDO::PARAM_INT);
        $stmt->bindValue(5, $like, \PDO::PARAM_STR);
        $stmt->bindValue(6, $like, \PDO::PARAM_STR);
        $stmt->bindValue(7, $like, \PDO::PARAM_STR);
        $stmt->bindValue(8, $like, \PDO::PARAM_STR);
        $stmt->execute();

        $rows = [];
        foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
            $row['snippet'] = mb_substr((string) $row['snippet'], 0, 300);
            $rows[] = $row;
        }

        return $rows;
    }

    /**
     * @return array<string, mixed>
     */
    private function demographics(int $pid): array
    {
        $stmt = $this->db->prepare(
            "SELECT pid, fname, lname, DATE_FORMAT(DOB, '%Y-%m-%d') AS dob, sex, race, ethnicity "
            . 'FROM patient_data WHERE pid = ?'
        );
        $stmt->bindValue(1, $pid, \PDO::PARAM_INT);
        $stmt->execute();

        $row = $stmt->fetch(\PDO::FETCH_ASSOC);

        return is_array($row) ? $row : [];
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function problems(int $pid): array
    {
        return $this->fetchList(
            "SELECT title, diagnosis, date FROM lists "
            . "WHERE pid = ? AND type = 'medical_problem' AND activity = 1",
            $pid
        );
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function medications(int $pid): array
    {
        return $this->fetchList(
            'SELECT drug, rxnorm_drugcode, date_added FROM prescriptions '
            . 'WHERE patient_id = ? AND active = 1',
            $pid
        );
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function allergies(int $pid): array
    {
        return $this->fetchList(
            "SELECT title FROM lists WHERE pid = ? AND type = 'allergy' AND activity = 1",
            $pid
        );
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function recentEncounters(int $pid): array
    {
        return $this->fetchList(
            'SELECT date, reason FROM form_encounter WHERE pid = ? '
            . 'ORDER BY date DESC LIMIT ' . (int) $this->recentLimit,
            $pid
        );
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function recentVitals(int $pid): array
    {
        return $this->fetchList(
            'SELECT date, bps, bpd, pulse, weight FROM form_vitals WHERE pid = ? '
            . 'ORDER BY date DESC LIMIT ' . (int) $this->recentLimit,
            $pid
        );
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function recentLabs(int $pid): array
    {
        return $this->fetchList(
            'SELECT pr.result_code, pr.result, pr.units, pr.date FROM procedure_result pr '
            . 'JOIN procedure_report prpt ON prpt.procedure_report_id = pr.procedure_report_id '
            . 'JOIN procedure_order po ON po.procedure_order_id = prpt.procedure_order_id '
            . 'WHERE po.patient_id = ? '
            . 'ORDER BY pr.date DESC LIMIT ' . (int) $this->recentLimit,
            $pid
        );
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function fetchList(string $sql, int $pid): array
    {
        $stmt = $this->db->prepare($sql);
        $stmt->bindValue(1, $pid, \PDO::PARAM_INT);
        $stmt->execute();

        return array_values($stmt->fetchAll(\PDO::FETCH_ASSOC));
    }
}
