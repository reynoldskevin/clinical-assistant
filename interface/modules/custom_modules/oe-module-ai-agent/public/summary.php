<?php

/**
 * summary.php — the AI agent's read boundary (HTTP).
 *
 * This endpoint is authenticated by the scoped JWT it receives, NOT by an
 * OpenEMR login session: the sidecar calls it server-to-server, forwarding the
 * short-lived, patient-scoped token that token.php minted for the clinician.
 * It therefore boots with $ignoreAuth — the token verification IS the
 * authorization, and it fails closed on any verification failure.
 *
 * Contract: POST JSON {"pid": <int>} with header "Authorization: Bearer <jwt>".
 * On success returns the minimum-necessary patient summary as JSON. The JWT is
 * bound to a single pid; a mismatch (or an invalid/expired token) yields 403 and
 * no chart data is read. No exception detail is ever surfaced to the caller.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

// Token-authenticated endpoint: skip the interactive login gate. globals.php
// still loads config, the DB, the autoloader, and the module namespace.
$ignoreAuth = true;
require_once __DIR__ . '/../../../../globals.php';

use OpenEMR\Common\Logging\SystemLogger;
use OpenEMR\Modules\AiAgent\Audit\DatabaseBoundaryAuditLogger;
use OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException;
use OpenEMR\Modules\AiAgent\Auth\ScopedTokenService;
use OpenEMR\Modules\AiAgent\Boundary\PatientSummaryEndpoint;
use OpenEMR\Modules\AiAgent\Service\PatientSummaryService;
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

// 1. Bearer token from the Authorization header (this is the credential).
//    Some Apache configurations do not expose it via $_SERVER, so fall back to
//    the request-headers API (and the mod_rewrite passthrough variable).
$authHeader = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '');
if ($authHeader === '' && function_exists('getallheaders')) {
    foreach (getallheaders() as $name => $value) {
        if (strcasecmp($name, 'Authorization') === 0) {
            $authHeader = (string) $value;
            break;
        }
    }
}
if (!str_starts_with($authHeader, 'Bearer ')) {
    $fail(401, 'Missing bearer token');
}
$jwt = trim(substr($authHeader, 7));

// 2. Requested patient from the JSON body. The token, not this value, decides
//    what may be read: a mismatch is rejected at verification.
$body = json_decode((string) file_get_contents('php://input'), true);
$pid = is_array($body) ? (int) ($body['pid'] ?? 0) : 0;
if ($pid <= 0) {
    $fail(400, 'Missing pid');
}

// 3. Shared signing key (same source as the mint endpoint).
$signingKey = Config::signingKey();
if ($signingKey === '') {
    (new SystemLogger())->error('AI agent signing key is not configured');
    $fail(500, 'Service unavailable');
}

// 4. Native PDO over the OpenEMR database (config loaded by globals.php).
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
} catch (\Throwable $e) {
    (new SystemLogger())->error('AI boundary DB connection failed', ['exception' => $e]);
    $fail(500, 'Service unavailable');
}

$clock = new class implements ClockInterface {
    public function now(): \DateTimeImmutable
    {
        return new \DateTimeImmutable();
    }
};

$endpoint = new PatientSummaryEndpoint(
    new ScopedTokenService($signingKey, $clock),
    new PatientSummaryService($pdo),
    new DatabaseBoundaryAuditLogger($pdo, $clock),
);

try {
    $summary = $endpoint->handle($jwt, $pid);
} catch (InvalidScopedTokenException $e) {
    // Wrong pid, expired, wrong audience, malformed — all fail closed, generic.
    $fail(403, 'Invalid or out-of-scope token');
} catch (\Throwable $e) {
    (new SystemLogger())->error('AI boundary read failed', ['exception' => $e]);
    $fail(500, 'Service unavailable');
}

echo json_encode($summary);
