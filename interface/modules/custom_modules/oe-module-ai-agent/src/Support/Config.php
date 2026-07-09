<?php

/**
 * Config — resolves the module's runtime secrets/settings.
 *
 * Values come from a gitignored local file (config.local.php at the module
 * root) or, failing that, environment variables. The HS256 signing key must
 * match between the mint endpoint (token.php) and the boundary endpoint
 * (summary.php); both read it from here so there is a single source of truth.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Support;

final class Config
{
    /** @var array<string, mixed>|null */
    private static ?array $cache = null;

    /**
     * The shared HS256 signing key (mint + verify). Empty string when unset.
     */
    public static function signingKey(): string
    {
        return self::stringValue('signing_key', 'OE_AI_AGENT_SIGNING_KEY');
    }

    /**
     * Absolute URL the browser posts questions to (the sidecar's /ask endpoint).
     */
    public static function sidecarUrl(): string
    {
        return self::stringValue('sidecar_url', 'OE_AI_AGENT_SIDECAR_URL');
    }

    private static function stringValue(string $key, string $envVar): string
    {
        $value = self::values()[$key] ?? null;
        if (is_string($value) && $value !== '') {
            return $value;
        }

        $env = getenv($envVar);

        return is_string($env) ? $env : '';
    }

    /**
     * @return array<string, mixed>
     */
    private static function values(): array
    {
        if (self::$cache !== null) {
            return self::$cache;
        }

        $file = dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'config.local.php';
        $loaded = is_file($file) ? require $file : [];
        self::$cache = is_array($loaded) ? $loaded : [];

        return self::$cache;
    }
}
