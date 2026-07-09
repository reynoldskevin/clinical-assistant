<?php

/**
 * Bootstrap for the AI Agent module - wires the module's event subscribers into OpenEMR.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent;

use OpenEMR\Modules\AiAgent\EventSubscriber\PatientSummarySubscriber;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

final class Bootstrap
{
    public function __construct(
        private readonly EventDispatcherInterface $eventDispatcher,
    ) {
    }

    public function subscribeToEvents(): void
    {
        $this->eventDispatcher->addSubscriber(new PatientSummarySubscriber());
    }
}
