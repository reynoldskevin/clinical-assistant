<?php

/**
 * ChartReadEndpoint — the single operation-dispatched, verify-before-read
 * boundary for the AI agent's chart reads.
 *
 * A scoped token (T08) is validated ONCE for the requested pid before any chart
 * data is fetched, then the request is dispatched to the provider by
 * ChartOperation via an exhaustive match. Any verification failure (cross-pid,
 * invalid, expired, wrong audience) propagates and NO provider method is called
 * — the boundary fails closed for every operation.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Boundary;

use OpenEMR\Modules\AiAgent\Audit\BoundaryAuditLoggerInterface;
use OpenEMR\Modules\AiAgent\Audit\NullBoundaryAuditLogger;
use OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException;
use OpenEMR\Modules\AiAgent\Auth\ScopedTokenService;
use OpenEMR\Modules\AiAgent\Service\ChartReadProviderInterface;

final class ChartReadEndpoint
{
    private readonly BoundaryAuditLoggerInterface $audit;

    public function __construct(
        private readonly ScopedTokenService $tokens,
        private readonly ChartReadProviderInterface $provider,
        ?BoundaryAuditLoggerInterface $audit = null,
    ) {
        $this->audit = $audit ?? new NullBoundaryAuditLogger();
    }

    /**
     * @param array<string, mixed> $params
     *
     * @return array<int|string, mixed>
     */
    public function handle(string $token, int $requestedPid, ChartOperation $op, array $params = []): array
    {
        // Verify first: throws InvalidScopedTokenException on any failure.
        // Only if verification succeeds do we read chart data (fail closed).
        try {
            $principal = $this->tokens->verify($token, $requestedPid);
        } catch (InvalidScopedTokenException $e) {
            // Record a generic reason — never leak the inner exception detail.
            $this->audit->recordDenied($requestedPid, 'invalid or out-of-scope token');
            throw $e;
        }

        $this->audit->recordGranted($principal);

        return match ($op) {
            ChartOperation::Summary => $this->provider->getSummary($requestedPid),
            ChartOperation::ListEncounters => $this->provider->listEncounters($requestedPid),
            ChartOperation::GetEncounter => $this->provider->getEncounter(
                $requestedPid,
                (int) ($params['encounter_id'] ?? 0),
            ),
            ChartOperation::GetResults => $this->provider->getResults($requestedPid),
        };
    }
}
