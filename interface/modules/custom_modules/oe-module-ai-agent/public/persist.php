<?php

/**
 * persist.php — the AI agent's clinician-gated fact-filing endpoint.
 *
 * The agent PROPOSES extracted facts (via /extract); this endpoint lets a
 * clinician COMMIT them to the chart. Like upload.php (and unlike the scoped-JWT
 * read boundary), it is an INTERACTIVE clinician action: it requires OpenEMR's
 * authenticated session, re-verifies the CSRF token, gates on the clinical read
 * ACL, and takes the patient scope from the session pid (never the wire). The
 * held fact envelope (source_document_id, extraction_run_id, doc_type, fact) is
 * dispatched by PersistFactsEndpoint to the matching persister, which
 * idempotently supersedes any prior run for the same document.
 *
 * Fail-closed by construction and never leaks internal detail.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

// OpenEMR globals + authenticated session bootstrap. If the session is not
// authenticated this bootstrap itself denies the request (fail closed).
require_once __DIR__ . '/../../../../globals.php';

use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Logging\SystemLogger;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Modules\AiAgent\Auth\ClinicalAccessPolicy;
use OpenEMR\Modules\AiAgent\Boundary\PersistFactsEndpoint;
use OpenEMR\Modules\AiAgent\Persistence\DerivedFactProvenanceService;
use OpenEMR\Modules\AiAgent\Persistence\IntakeFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\LabFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\MedicationFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\NarrativeFieldSplitter;

// The persisters and endpoint are plain module classes; the module namespace is
// registered by the bootstrap, but the persisters guard their own deps with
// require_once, so pull them in explicitly here too (mirrors upload.php's
// direct-require style for module collaborators).
$srcPersist = __DIR__ . '/../src/Persistence/';
require_once $srcPersist . 'DerivedFactRef.php';
require_once $srcPersist . 'DerivedFactProvenanceService.php';
require_once $srcPersist . 'NarrativeFieldSplitter.php';
require_once $srcPersist . 'LabFactPersister.php';
require_once $srcPersist . 'IntakeFactPersister.php';
require_once $srcPersist . 'MedicationFactPersister.php';
require_once __DIR__ . '/../src/Boundary/PersistFactsEndpoint.php';

header('Content-Type: application/json');

/**
 * Emit a generic JSON error and stop. Never leaks internal detail.
 */
$fail = static function (int $status, string $message): never {
    http_response_code($status);
    echo json_encode(['error' => $message]);
    exit;
};

$session = SessionWrapperFactory::getInstance()->getActiveSession();

// 1. Authenticated session required.
$clinicianId = (int) $session->get('authUserID');
$clinicianUsername = (string) $session->get('authUser');
if ($clinicianId <= 0 || $clinicianUsername === '') {
    $fail(401, 'Not authenticated');
}

// 2. CSRF must verify before anything is written.
if (!CsrfUtils::verifyCsrfToken($_POST['csrf_token'] ?? '', session: $session)) {
    $fail(403, 'Invalid CSRF token');
}

// 3. Clinical authorization gate: reuse the same read gate the mint/upload
//    endpoints use — a clinician who may read this chart may file to it.
$policy = new ClinicalAccessPolicy(AclMain::aclCheckCore(...));
if (!$policy->mayReadClinical($clinicianUsername)) {
    $fail(403, 'Not authorized');
}

// 4. Patient scope from the session (never the wire).
$pid = (int) $session->get('pid');
if ($pid <= 0) {
    $fail(400, 'No patient in context');
}

// 5. Parse and validate the held fact envelope.
$payload = json_decode((string) ($_POST['payload'] ?? ''), true);
if (!is_array($payload)) {
    $fail(400, 'Invalid request');
}

$sourceDocumentId = (int) ($payload['source_document_id'] ?? 0);
if ($sourceDocumentId <= 0) {
    $fail(400, 'Invalid document');
}

$docType = (string) ($payload['doc_type'] ?? '');
if (!in_array($docType, ['lab_pdf', 'intake_form', 'med_list'], true)) {
    $fail(400, 'Invalid document type');
}

$fact = $payload['fact'] ?? null;
if (!is_array($fact)) {
    $fail(400, 'Invalid facts');
}

$extractionRunId = (string) ($payload['extraction_run_id'] ?? '');

// 6. Build the PDO from $GLOBALS exactly like upload.php, wire the persisters
//    and the endpoint, then dispatch.
try {
    $pdo = new \PDO(
        sprintf(
            'mysql:host=%s;port=%s;dbname=%s',
            (string) ($GLOBALS['host'] ?? 'localhost'),
            (string) ($GLOBALS['port'] ?? '3306'),
            (string) ($GLOBALS['dbase'] ?? ''),
        ),
        (string) ($GLOBALS['login'] ?? ''),
        (string) ($GLOBALS['pass'] ?? ''),
        [
            \PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION,
            \PDO::ATTR_DEFAULT_FETCH_MODE => \PDO::FETCH_ASSOC,
        ],
    );

    $provenance = new DerivedFactProvenanceService($pdo);
    $endpoint = new PersistFactsEndpoint(
        new LabFactPersister($pdo, $provenance),
        new IntakeFactPersister($pdo, $provenance, new NarrativeFieldSplitter()),
        new MedicationFactPersister($pdo, $provenance, new NarrativeFieldSplitter()),
    );

    $result = $endpoint->handle(
        $pid,
        $sourceDocumentId,
        $extractionRunId,
        $docType,
        $fact,
        $clinicianId,
        $clinicianUsername,
    );
} catch (\DomainException $e) {
    // An unsupported doc_type slipped past validation — generic 400, no detail.
    $fail(400, 'Invalid document type');
} catch (\Throwable $e) {
    // Never surface internal detail; log the failure with pid + doc_type only.
    (new SystemLogger())->error('AI agent fact filing failed', [
        'pid' => $pid,
        'doc_type' => $docType,
        'exception' => $e,
    ]);
    $fail(500, 'Could not file to the chart');
}

echo json_encode($result);
