<?php

/**
 * upload.php — the AI agent's guarded document-upload endpoint.
 *
 * Unlike read.php / summary.php (which are authenticated by a scoped JWT and
 * boot with $ignoreAuth), this is an INTERACTIVE clinician action: it requires
 * OpenEMR's authenticated session, re-verifies the CSRF token, and only then
 * stores the uploaded file. The patient scope comes from the session pid (never
 * the wire), so a clinician can only file a document against the patient they
 * already have in context. The chosen doc_type (lab_pdf | intake_form) is
 * recorded on the row's `documentationOf` column so getDocuments maps it back to
 * `doc_type`. VLM extraction is out of scope here — this endpoint only stores.
 *
 * Fail-closed by construction and never leaks internal detail; raw document
 * bytes/text are NEVER logged.
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

// 1. Authenticated session required. Auth state lives in the session wrapper,
//    not the $_SESSION superglobal, so read it through the wrapper.
$clinicianId = (int) $session->get('authUserID');
$clinicianUsername = (string) $session->get('authUser');
if ($clinicianId <= 0 || $clinicianUsername === '') {
    $fail(401, 'Not authenticated');
}

// 2. CSRF must verify before anything is stored.
if (!CsrfUtils::verifyCsrfToken($_POST['csrf_token'] ?? '', session: $session)) {
    $fail(403, 'Invalid CSRF token');
}

// 3. Clinical-write authorization gate: the agent must never let a clinician do
//    more than OpenEMR's own ACL allows. Reuse the same read gate the mint
//    endpoint uses — a clinician who may read this chart may attach to it.
$policy = new ClinicalAccessPolicy(AclMain::aclCheckCore(...));
if (!$policy->mayReadClinical($clinicianUsername)) {
    $fail(403, 'Not authorized');
}

// 4. Patient scope from the session (never the wire).
$pid = (int) $session->get('pid');
if ($pid <= 0) {
    $fail(400, 'No patient in context');
}

// 5. Parse the doc_type into the closed set the read side understands.
$docType = (string) ($_POST['doc_type'] ?? '');
if (!in_array($docType, ['lab_pdf', 'intake_form'], true)) {
    $fail(400, 'Invalid document type');
}

// 6. The uploaded file. Happy path only: assume a valid PDF/image of reasonable
//    size. Reject only the clear failure cases.
$file = $_FILES['document'] ?? null;
if (!is_array($file) || ($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
    $fail(400, 'No file uploaded');
}
$tmpPath = (string) ($file['tmp_name'] ?? '');
if ($tmpPath === '' || !is_uploaded_file($tmpPath)) {
    $fail(400, 'No file uploaded');
}

$data = (string) @file_get_contents($tmpPath);
if ($data === '') {
    $fail(400, 'Empty file');
}

$name = (string) ($file['name'] ?? 'document');
$mimetype = (string) ($file['type'] ?? 'application/octet-stream');
if ($mimetype === '') {
    $mimetype = 'application/octet-stream';
}

// 6b. Resolve a valid, FK-safe document category for the chosen doc_type. Look
//     the category up by name from OpenEMR's own `categories` table so the id we
//     hand \Document::createDocument() always satisfies the
//     categories_to_documents FK; fall back to the tree root (id 1) — which
//     always exists in a seeded install — if the preferred category is absent.
$categoryName = $docType === 'lab_pdf' ? 'Lab Report' : 'Patient Information';
$categoryRow = sqlQuery('SELECT id FROM categories WHERE name = ? LIMIT 1', [$categoryName]);
$categoryId = (isset($categoryRow['id']) && is_numeric($categoryRow['id'])) ? (int) $categoryRow['id'] : 1;

// Build the human-readable breadcrumb to the chosen category (e.g.
// "Documents > Patient Information") so the widget can confirm exactly where the
// file was filed. Walk the category nested set from the tree root down to the
// chosen node: every category whose [lft, rght] span contains the node is an
// ancestor-or-self, and ordering by lft yields root-first. The generic tree
// root (parent 0) is presented as "Documents" — the section name the clinician
// actually sees — and any real ancestor categories below it are included so a
// nested category still renders its full path.
$ancestors = sqlStatement(
    'SELECT c.name, c.parent
       FROM categories c
       JOIN categories node ON node.id = ?
      WHERE c.lft <= node.lft AND c.rght >= node.rght
      ORDER BY c.lft',
    [$categoryId]
);
$segments = ['Documents'];
while ($row = sqlFetchArray($ancestors)) {
    if ((int) $row['parent'] === 0) {
        // The tree root is represented by the "Documents" segment above.
        continue;
    }
    $segments[] = (string) $row['name'];
}
$categoryPath = implode(' > ', $segments);

// 7. Store the file through OpenEMR's real document layer (audit trail, category,
//    filesystem storage). createDocument() returns '' on success and an error
//    string on failure; it sets foreign_id to the patient and links the category.
//
//    Deliberate double-store: \Document writes the bytes to the FILESYSTEM (read
//    back via \Document::get_data()), but the AI read boundary (getDocument) reads
//    JSON-safe content out of the row's `document_data` column. So after the real
//    store we ALSO persist base64 of the bytes into document_data on the same row
//    (plus the chosen doc_type on documentationOf). Base64 is required so read.php
//    can json_encode the content and it matches the DocumentContent contract.
//    Dropping this column copy once read.php fetches via \Document::get_data() is
//    a deferred cleanup.
try {
    $document = new \Document();
    $result = $document->createDocument($pid, $categoryId, $name, $mimetype, $data);
    if ($result !== '') {
        // createDocument signals failure with a non-empty (already-translated)
        // message. Never surface it to the caller; log the failure only.
        throw new \RuntimeException('createDocument reported a storage failure');
    }

    $documentId = (int) $document->get_id();
    if ($documentId <= 0) {
        throw new \RuntimeException('createDocument did not yield a document id');
    }

    // Persist the AI-read-path columns on the freshly-created row via OpenEMR's
    // own DB API (available after globals.php) — not a fresh PDO.
    sqlStatementThrowException(
        'UPDATE documents SET documentationOf = ?, document_data = ? WHERE id = ?',
        [$docType, base64_encode($data), $documentId]
    );
} catch (\Throwable $e) {
    // Never log raw document bytes/text; only the failure, pid, and doc_type.
    (new SystemLogger())->error('AI agent document upload failed', [
        'pid' => $pid,
        'doc_type' => $docType,
        'exception' => $e,
    ]);
    $fail(500, 'Could not store document');
}

// Return the resolved category name so the widget can confirm to the clinician
// exactly where the document was filed (the doc_type -> category mapping is not
// otherwise visible on the card).
echo json_encode(['ok' => true, 'id' => $documentId, 'category' => $categoryPath]);
