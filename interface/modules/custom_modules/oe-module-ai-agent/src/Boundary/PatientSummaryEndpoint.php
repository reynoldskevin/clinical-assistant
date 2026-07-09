<?php

/**
 * PatientSummaryEndpoint — verify-before-read boundary for the AI agent.
 *
 * A scoped token (T08) is validated before any chart data is fetched. If
 * verification fails for any reason (cross-pid, invalid, expired, wrong
 * audience), the exception propagates and the summary provider is never
 * touched — the boundary fails closed.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Boundary;

use OpenEMR\Modules\AiAgent\Auth\ScopedTokenService;
use OpenEMR\Modules\AiAgent\Service\PatientSummaryProviderInterface;

final class PatientSummaryEndpoint
{
    public function __construct(
        private readonly ScopedTokenService $tokens,
        private readonly PatientSummaryProviderInterface $summaries,
    ) {
    }

    /**
     * @return array<string, mixed>
     */
    public function handle(string $token, int $requestedPid): array
    {
        // Verify first: throws InvalidScopedTokenException on any failure.
        // Only if verification succeeds do we read chart data (fail closed).
        $this->tokens->verify($token, $requestedPid);

        return $this->summaries->getSummary($requestedPid);
    }
}
