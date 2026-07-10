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
