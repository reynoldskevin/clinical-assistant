<?php

/**
 * T53c acceptance tests (LOCKED) — NarrativeFieldSplitter.
 *
 * Pure, no DB. Splits a narrative IntakeFact field (e.g. current_medications) into
 * discrete line-items on `;` and newlines (NOT commas — a dosage must stay intact),
 * trims, and drops empties + negation sentinels ("none", "NKDA", "no known …", "—").
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Persistence;

use OpenEMR\Modules\AiAgent\Persistence\NarrativeFieldSplitter;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/NarrativeFieldSplitter.php';

#[Group('isolated')]
final class NarrativeFieldSplitterTest extends TestCase
{
    public function testSplitsSemicolonSeparatedMedications(): void
    {
        $items = (new NarrativeFieldSplitter())->split(
            'Lisinopril 10 mg once daily; Metformin 500 mg twice daily; Atorvastatin 20 mg at night.'
        );
        $this->assertCount(3, $items);
        $this->assertSame('Lisinopril 10 mg once daily', $items[0]);
        $this->assertStringContainsString('Metformin 500 mg twice daily', $items[1]);
    }

    public function testSplitsOnNewlines(): void
    {
        $items = (new NarrativeFieldSplitter())->split("Father: MI at 60\nMother: type 2 diabetes");
        $this->assertCount(2, $items);
        $this->assertStringContainsString('Father', $items[0]);
        $this->assertStringContainsString('Mother', $items[1]);
    }

    public function testDoesNotSplitOnCommasWithinADosage(): void
    {
        $items = (new NarrativeFieldSplitter())->split('Aspirin 81 mg, once daily');
        $this->assertCount(1, $items);
        $this->assertSame('Aspirin 81 mg, once daily', $items[0]);
    }

    public function testDropsEmptySegmentsAndTrims(): void
    {
        $items = (new NarrativeFieldSplitter())->split('  Aspirin ;;  Warfarin ; ');
        $this->assertSame(['Aspirin', 'Warfarin'], $items);
    }

    public function testKeepsASingleRealItem(): void
    {
        $items = (new NarrativeFieldSplitter())->split('Penicillin (rash).');
        $this->assertCount(1, $items);
        $this->assertStringContainsString('Penicillin', $items[0]);
    }

    /**
     * @return array<string, array{string}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function negationProvider(): array
    {
        return [
            'none' => ['None'],
            'none period' => ['none.'],
            'nkda' => ['NKDA'],
            'no known drug allergies' => ['No known drug allergies'],
            'no known allergies' => ['no known allergies'],
            'n/a' => ['N/A'],
            'na' => ['NA'],
            'emdash' => ['—'],
            'dash' => ['-'],
            'blank' => ['   '],
            'empty' => [''],
            'denies' => ['Denies'],
        ];
    }

    #[DataProvider('negationProvider')]
    public function testDropsNegationSentinels(string $input): void
    {
        $this->assertSame([], (new NarrativeFieldSplitter())->split($input));
    }

    public function testNegationMixedWithRealItems(): void
    {
        // A negation among real items drops only the negation.
        $items = (new NarrativeFieldSplitter())->split('Penicillin; none; Sulfa');
        $this->assertSame(['Penicillin', 'Sulfa'], $items);
    }
}
