<?php

/**
 * Subscribes to the patient summary card render event so the AI Agent can add its card.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\EventSubscriber;

use OpenEMR\Events\Patient\Summary\Card\RenderEvent;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;

final class PatientSummarySubscriber implements EventSubscriberInterface
{
    /**
     * @return array<string, string>
     */
    public static function getSubscribedEvents(): array
    {
        return [
            RenderEvent::EVENT_HANDLE => 'onRenderPatientSummary',
        ];
    }

    public function onRenderPatientSummary(RenderEvent $event): void
    {
        // Placeholder: the actual patient-summary card is added in T16.
    }
}
