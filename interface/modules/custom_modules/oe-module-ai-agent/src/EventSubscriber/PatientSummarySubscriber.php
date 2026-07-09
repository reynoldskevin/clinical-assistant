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

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\OEGlobalsBag;
use OpenEMR\Events\Patient\Summary\Card\RenderEvent;
use OpenEMR\Events\PatientDemographics\RenderEvent as DemographicsRenderEvent;
use OpenEMR\Modules\AiAgent\Support\Config;
use OpenEMR\Modules\AiAgent\Ui\AgentCard;
use OpenEMR\Modules\AiAgent\Ui\AgentCardRenderable;
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
            DemographicsRenderEvent::EVENT_SECTION_LIST_RENDER_TOP => 'onRenderDemographicsTop',
        ];
    }

    public function onRenderPatientSummary(RenderEvent $event): void
    {
        // The current patient in scope for the summary being rendered (set by
        // globals.php as $globalsBag->set('pid', ...)).
        $pid = OEGlobalsBag::getInstance()->getInt('pid');
        if ($pid <= 0) {
            return;
        }

        $event->addAppendedData(new AgentCardRenderable($pid));
    }

    /**
     * Render the AI Co-Pilot card at the top of the patient dashboard.
     *
     * Listeners of the demographics render-top event write directly to the page
     * output stream (the event is dispatched inline, with no output capture), so
     * this is the reliable in-page injection point for the card.
     */
    public function onRenderDemographicsTop(DemographicsRenderEvent $event): void
    {
        $pid = OEGlobalsBag::getInstance()->getInt('pid');
        if ($pid <= 0) {
            return;
        }

        // Embed a session-bound CSRF token the widget sends back to token.php;
        // the dashboard page does not expose one as a JS global.
        $session = SessionWrapperFactory::getInstance()->getActiveSession();
        $csrfToken = CsrfUtils::collectCsrfToken($session);

        echo AgentCard::render($pid, Config::sidecarUrl(), $csrfToken);
    }
}
