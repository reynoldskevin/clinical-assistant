<?php

/**
 * NarrativeFieldSplitter — breaks a narrative IntakeFact field (e.g.
 * current_medications, allergies, family_history) into discrete line-items.
 *
 * Splits ONLY on `;` and newlines (never commas — a dosage like "10 mg, twice
 * daily" must stay intact), trims each item, and drops empties plus negation
 * sentinels ("none", "NKDA", "no known …", "—"). This is deterministic,
 * demo-grade line-splitting — not clinical NLP.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Persistence;

final class NarrativeFieldSplitter
{
    /**
     * Case-insensitive negation sentinels, compared after trimming and stripping
     * a trailing period/whitespace from the item.
     *
     * @var list<string>
     */
    private const NEGATIONS = [
        'none',
        'n/a',
        'na',
        'nkda',
        'no known drug allergies',
        'no known allergies',
        'no known',
        'denies',
        'denied',
        'not reported',
        'none reported',
        'none known',
        '—',
        '-',
    ];

    /**
     * @return list<string>
     */
    public function split(string $narrative): array
    {
        $parts = preg_split('/[;\r\n]+/', $narrative) ?: [];

        $items = [];
        foreach ($parts as $part) {
            $trimmed = trim($part);
            if ($trimmed === '') {
                continue;
            }
            if ($this->isNegation($trimmed)) {
                continue;
            }
            $items[] = $trimmed;
        }

        return array_values($items);
    }

    private function isNegation(string $item): bool
    {
        $normalized = strtolower(rtrim($item, ". \t\n\r\0\x0B"));
        if ($normalized === '') {
            return true;
        }

        return in_array($normalized, self::NEGATIONS, true);
    }
}
