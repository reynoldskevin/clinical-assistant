<?php

/**
 * dev_mint.php — DEV/DEMO-ONLY unauthenticated token mint endpoint.
 *
 * ============================ DANGER / READ ME ============================
 * This endpoint is DEV/DEMO-ONLY and intended solely for the synthetic demo
 * dataset. It is DISABLED BY DEFAULT and returns 404 when the dev-mint gate
 * (Config::devMintEnabled(): dev_token_mint / OE_AI_AGENT_DEV_MINT) is off.
 * It bypasses OpenEMR's session, CSRF, and ACL controls BY DESIGN so a
 * Postman collection can mint a pid-scoped JWT programmatically. It MUST
 * NEVER be enabled on an instance holding real PHI.
 * =========================================================================
 *
 * When enabled it reads a pid from the JSON body or query, mints an ordinary
 * pid-scoped token via DevTokenMinter, and returns it. No exception detail is
 * ever surfaced to the caller.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

// Unauthenticated by design — this is a dev helper, no session needed. Tell the
// OpenEMR bootstrap to skip its authenticated-session gate. The dev-mint gate
// (checked first, below) is the primary control that keeps this fail-closed.
$ignoreAuth = true;

require_once __DIR__ . '/../../../../globals.php';

use OpenEMR\Common\Logging\SystemLogger;
use OpenEMR\Modules\AiAgent\Auth\DevTokenMinter;
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

// 1. Dev-mint gate. Fail-closed: return 404 when disabled so the endpoint does
//    not advertise itself on production instances.
if (!Config::devMintEnabled()) {
    $fail(404, 'Not found');
}

// 2. Read pid (and optional clinician_id / username) from the JSON body or query.
$raw = file_get_contents('php://input');
$body = is_string($raw) && $raw !== '' ? json_decode($raw, true) : null;
$body = is_array($body) ? $body : [];

$pid = (int) ($body['pid'] ?? $_GET['pid'] ?? 0);
if ($pid <= 0) {
    $fail(400, 'Missing pid');
}

$clinicianId = (int) ($body['clinician_id'] ?? $_GET['clinician_id'] ?? 1);
$username = (string) ($body['username'] ?? $_GET['username'] ?? 'dev');
if ($clinicianId <= 0) {
    $clinicianId = 1;
}
if ($username === '') {
    $username = 'dev';
}

// 3. Signing key from server configuration (never sent to the browser).
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
    // Gate already verified above; pass true explicitly.
    $jwt = (new DevTokenMinter(true, $signingKey, $clock))->mintForPid($pid, $clinicianId, $username);
} catch (\Throwable $e) {
    // Never expose the inner message (may reveal key length, config, etc.).
    (new SystemLogger())->error('AI agent dev token mint failed', ['exception' => $e]);
    $fail(500, 'Could not mint token');
}

echo json_encode(['token' => $jwt, 'pid' => $pid]);
