<?php

/**
 * token.php — the AI agent's scoped-token mint endpoint.
 *
 * Fail-closed by construction: it requires OpenEMR's authenticated-session
 * bootstrap, re-verifies the CSRF token, and only then mints a short-lived,
 * patient-scoped JWT bound to the session's clinician and active patient. The
 * signing key is read from server configuration and never leaves the server;
 * the browser only ever receives the resulting token. No exception detail is
 * ever surfaced to the caller.
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
use OpenEMR\Modules\AiAgent\Auth\TokenMinter;
use OpenEMR\Modules\AiAgent\Support\Config;
use Psr\Clock\ClockInterface;

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

// 1. Authenticated session required. OpenEMR keeps auth state in the session
//    wrapper, not the $_SESSION superglobal, so read it through the wrapper.
$clinicianId = (int) $session->get('authUserID');
$clinicianUsername = (string) $session->get('authUser');
if ($clinicianId <= 0 || $clinicianUsername === '') {
    $fail(401, 'Not authenticated');
}

// 2. CSRF must verify before anything is minted.
if (!CsrfUtils::verifyCsrfToken($_POST['csrf_token'] ?? '', session: $session)) {
    $fail(403, 'Invalid CSRF token');
}

// 3. Clinical-read authorization gate. The agent must never read more than the
//    logged-in human could, so delegate to OpenEMR's own ACL before minting.
$policy = new ClinicalAccessPolicy(AclMain::aclCheckCore(...));
if (!$policy->mayReadClinical($clinicianUsername)) {
    $fail(403, 'Not authorized');
}

// 4. Patient scope from the session.
$pid = (int) $session->get('pid');
if ($pid <= 0) {
    $fail(400, 'No patient in context');
}

// 5. Signing key from server configuration (never sent to the browser).
$signingKey = Config::signingKey();
if ($signingKey === '') {
    (new SystemLogger())->error('AI agent signing key is not configured');
    $fail(500, 'Service unavailable');
}

// Native PSR-20 clock — deterministic wall-clock, no service-locator reach.
$clock = new class implements ClockInterface {
    public function now(): \DateTimeImmutable
    {
        return new \DateTimeImmutable();
    }
};

try {
    $jwt = TokenMinter::mint($clinicianId, $clinicianUsername, $pid, $signingKey, $clock);
} catch (\Throwable $e) {
    // Never expose the inner message (may reveal key length, config, etc.).
    (new SystemLogger())->error('AI agent token mint failed', ['exception' => $e]);
    $fail(500, 'Could not mint token');
}

echo json_encode(['token' => $jwt]);
