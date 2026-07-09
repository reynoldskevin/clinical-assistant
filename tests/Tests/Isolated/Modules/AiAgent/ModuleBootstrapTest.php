<?php

/**
 * T07 acceptance tests (LOCKED) — oe-module-ai-agent skeleton.
 *
 * Verifies the module registers an event subscriber on the patient-summary card
 * render event and that its composer.json declares a valid openemr-module. Isolated
 * (no DB): registration is exercised against a real Symfony EventDispatcher.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent;

use OpenEMR\Events\Patient\Summary\Card\RenderEvent;
use OpenEMR\Modules\AiAgent\Bootstrap;
use OpenEMR\Modules\AiAgent\EventSubscriber\PatientSummarySubscriber;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Symfony\Component\EventDispatcher\EventDispatcher;

// The module has its own PSR-4 (module composer.json), not the root autoloader,
// so load its classes explicitly for the isolated test.
require_once __DIR__ . '/../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Bootstrap.php';
require_once __DIR__ . '/../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/EventSubscriber/PatientSummarySubscriber.php';

#[Group('isolated')]
final class ModuleBootstrapTest extends TestCase
{
    private const MODULE_ROOT =
        __DIR__ . '/../../../../../interface/modules/custom_modules/oe-module-ai-agent';

    public function testSubscriberListensToPatientSummaryCardRender(): void
    {
        $events = PatientSummarySubscriber::getSubscribedEvents();
        $this->assertArrayHasKey(RenderEvent::EVENT_HANDLE, $events);

        $handler = $events[RenderEvent::EVENT_HANDLE];
        $method = is_array($handler) ? $handler[0] : $handler;
        $this->assertIsString($method);
        $this->assertTrue(
            method_exists(PatientSummarySubscriber::class, $method),
            "handler method {$method} must exist"
        );
    }

    public function testBootstrapRegistersSubscriberOnDispatcher(): void
    {
        $dispatcher = new EventDispatcher();
        (new Bootstrap($dispatcher))->subscribeToEvents();
        $this->assertTrue(
            $dispatcher->hasListeners(RenderEvent::EVENT_HANDLE),
            'Bootstrap::subscribeToEvents() must register a listener on the card render event'
        );
    }

    public function testModuleComposerDeclaresOpenemrModuleAndPsr4(): void
    {
        $path = self::MODULE_ROOT . '/composer.json';
        $this->assertFileExists($path);

        $composer = json_decode((string) file_get_contents($path), true);
        $this->assertIsArray($composer);
        $this->assertSame('openemr-module', $composer['type'] ?? null);
        $this->assertArrayHasKey(
            'OpenEMR\\Modules\\AiAgent\\',
            $composer['autoload']['psr-4'] ?? []
        );
    }

    public function testBootstrapEntryFileExists(): void
    {
        // runtime glue that OpenEMR loads to boot the module
        $this->assertFileExists(self::MODULE_ROOT . '/openemr.bootstrap.php');
    }
}
