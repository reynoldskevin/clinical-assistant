<?php

/**
 * read.php — the AI agent's operation-dispatched read boundary (HTTP).
 *
 * The single HTTP entry for ALL chart reads (summary + chart navigation). Like
 * summary.php, it is authenticated by the scoped JWT it receives, NOT by an
 * OpenEMR login session: the sidecar calls it server-to-server, forwarding the
 * short-lived, patient-scoped token that token.php minted for the clinician. It
 * therefore boots with $ignoreAuth — the token verification IS the
 * authorization, and it fails closed on any verification failure.
 *
 * Contract: POST JSON {"op": <string>, "pid": <int>, "params": {...}} with
 * header "Authorization: Bearer <jwt>". The raw op string is PARSED into the
 * ChartOperation whitelist; an unrecognized op is rejected 400 before any token
 * work. The JWT is bound to a single pid; a mismatch (or invalid/expired token)
 * yields 403 and no chart data is read. No exception detail is ever surfaced.
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
use OpenEMR\Modules\AiAgent\Boundary\ChartOperation;
use OpenEMR\Modules\AiAgent\Boundary\ChartReadEndpoint;
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

// 1b. Correlation id (forwarded by the sidecar as X-Correlation-ID). Read with
//     the same robustness as the Authorization header. Absence is not an error.
$correlationId = (string) ($_SERVER['HTTP_X_CORRELATION_ID'] ?? '');
if ($correlationId === '' && function_exists('getallheaders')) {
    foreach (getallheaders() as $name => $value) {
        if (strcasecmp($name, 'X-Correlation-ID') === 0) {
            $correlationId = (string) $value;
            break;
        }
    }
}
$correlationId = trim($correlationId);
$correlationId = $correlationId === '' ? null : $correlationId;

// 2. Parse the request body. The operation is PARSED into the whitelist first:
//    an unrecognized op is rejected before any token work is done.
$body = json_decode((string) file_get_contents('php://input'), true);
$op = ChartOperation::tryFrom(is_array($body) ? (string) ($body['op'] ?? '') : '');
if ($op === null) {
    $fail(400, 'Unknown operation');
}

// 3. Requested patient from the JSON body. The token, not this value, decides
//    what may be read: a mismatch is rejected at verification.
$pid = is_array($body) ? (int) ($body['pid'] ?? 0) : 0;
if ($pid <= 0) {
    $fail(400, 'Missing pid');
}

$params = (is_array($body) && is_array($body['params'] ?? null)) ? $body['params'] : [];

// 4. Shared signing key (same source as the mint endpoint).
$signingKey = Config::signingKey();
if ($signingKey === '') {
    (new SystemLogger())->error('AI agent signing key is not configured');
    $fail(500, 'Service unavailable');
}

// 5. Native PDO over the OpenEMR database (config loaded by globals.php).
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

$endpoint = new ChartReadEndpoint(
    new ScopedTokenService($signingKey, $clock),
    new PatientSummaryService($pdo),
    new DatabaseBoundaryAuditLogger($pdo, $clock, $correlationId),
);

try {
    $result = $endpoint->handle($jwt, $pid, $op, $params);
} catch (InvalidScopedTokenException $e) {
    // Wrong pid, expired, wrong audience, malformed — all fail closed, generic.
    $fail(403, 'Invalid or out-of-scope token');
} catch (\Throwable $e) {
    (new SystemLogger())->error('AI boundary read failed', ['exception' => $e]);
    $fail(500, 'Service unavailable');
}

echo json_encode($result);
