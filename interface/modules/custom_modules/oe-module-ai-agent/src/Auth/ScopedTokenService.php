<?php

/**
 * Mints and verifies short-lived, patient-scoped JWTs for the AI agent.
 *
 * Implements the custom-JWT auth model (ARCHITECTURE §1a): each token is bound
 * to a single clinician, a single patient scope, and a fixed audience, and
 * expires after a short TTL. Signing/verification is delegated to
 * firebase/php-jwt (HS256); no crypto is hand-rolled here. Time is supplied by
 * an injected PSR-20 clock so expiry is deterministic and testable.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

use Firebase\JWT\JWT;
use Firebase\JWT\Key;
use Psr\Clock\ClockInterface;

final class ScopedTokenService
{
    public function __construct(
        private readonly string $signingKey,
        private readonly ClockInterface $clock,
        private readonly string $audience = 'oe-ai-agent-boundary',
        private readonly int $ttlSeconds = 300,
    ) {
    }

    public function mint(ClinicalPrincipal $principal): string
    {
        $now = $this->clock->now()->getTimestamp();

        $payload = [
            'cid' => $principal->clinicianId,
            'usr' => $principal->clinicianUsername,
            'pid' => $principal->patientId->value,
            'purpose' => $principal->purpose,
            'aud' => $this->audience,
            'iat' => $now,
            'exp' => $now + $this->ttlSeconds,
            'scope' => 'read',
        ];

        return JWT::encode($payload, $this->signingKey, 'HS256');
    }

    public function verify(string $token, int $requestedPid): ClinicalPrincipal
    {
        try {
            JWT::$timestamp = $this->clock->now()->getTimestamp();

            $claims = JWT::decode($token, new Key($this->signingKey, 'HS256'));

            if ($claims->aud !== $this->audience) {
                throw new InvalidScopedTokenException('Scoped token rejected');
            }

            if (((int) $claims->pid) !== $requestedPid) {
                throw new InvalidScopedTokenException('Scoped token rejected');
            }

            return new ClinicalPrincipal(
                (int) $claims->cid,
                (string) $claims->usr,
                new PatientId((int) $claims->pid),
                (string) $claims->purpose,
            );
        } catch (\Throwable $e) {
            throw new InvalidScopedTokenException('Scoped token rejected', 0, $e);
        } finally {
            JWT::$timestamp = null;
        }
    }
}
