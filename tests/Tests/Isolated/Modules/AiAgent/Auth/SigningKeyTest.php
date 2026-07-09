<?php

/**
 * T09c acceptance tests (LOCKED) — SigningKey value object.
 *
 * Refuses a weak HS256 secret (< 32 bytes) at construction. Isolated: pure value object.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Auth;

use OpenEMR\Modules\AiAgent\Auth\SigningKey;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Auth/SigningKey.php';

#[Group('isolated')]
final class SigningKeyTest extends TestCase
{
    public function testAcceptsExactly32ByteKey(): void
    {
        $key = str_repeat('a', 32);
        $this->assertSame($key, (new SigningKey($key))->value);
    }

    public function testAcceptsLongerKey(): void
    {
        $key = str_repeat('x', 64);
        $this->assertSame($key, (new SigningKey($key))->value);
    }

    public function testRejectsShortKey(): void
    {
        $this->expectException(\DomainException::class);
        new SigningKey(str_repeat('a', 31));
    }

    public function testRejectsEmptyKey(): void
    {
        $this->expectException(\DomainException::class);
        new SigningKey('');
    }

    public function testIsReadonlyAndFinal(): void
    {
        $ref = new \ReflectionClass(SigningKey::class);
        $this->assertTrue($ref->isFinal());
        $this->assertTrue($ref->isReadOnly());
    }
}
