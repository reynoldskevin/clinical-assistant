<?php

/**
 * T17 acceptance tests (LOCKED) — ChartOperation enum.
 *
 * The closed set of read operations the multi-tool boundary dispatches to. A raw
 * operation string from the wire is PARSED into this enum (parse, don't
 * validate); an unrecognized string must be rejected, not silently accepted.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Boundary;

use OpenEMR\Modules\AiAgent\Boundary\ChartOperation;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Boundary/ChartOperation.php';

#[Group('isolated')]
final class ChartOperationTest extends TestCase
{
    public function testExactlyTheExpectedOperationsExist(): void
    {
        $values = array_map(static fn (ChartOperation $c): string => $c->value, ChartOperation::cases());

        // Exactly these, no more: the boundary's whitelist (T18 adds get_results).
        $this->assertSame(['summary', 'list_encounters', 'get_encounter', 'get_results'], $values);
    }

    public function testValidStringsParseToTheMatchingCase(): void
    {
        $this->assertSame(ChartOperation::Summary, ChartOperation::from('summary'));
        $this->assertSame(ChartOperation::ListEncounters, ChartOperation::from('list_encounters'));
        $this->assertSame(ChartOperation::GetEncounter, ChartOperation::from('get_encounter'));
        $this->assertSame(ChartOperation::GetResults, ChartOperation::from('get_results'));
    }

    public function testUnknownStringIsRejected(): void
    {
        $this->expectException(\ValueError::class);
        ChartOperation::from('drop_tables');
    }

    public function testTryFromReturnsNullForUnknown(): void
    {
        $this->assertNull(ChartOperation::tryFrom('bogus'));
    }
}
