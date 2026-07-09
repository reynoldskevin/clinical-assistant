<?php

/**
 * Runtime entry file the OpenEMR module loader executes to boot the AI Agent module.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent;

/**
 * @var \OpenEMR\Core\ModulesClassLoader $classLoader Injected by the OpenEMR module loader.
 */
$classLoader->registerNamespaceIfNotExists('OpenEMR\\Modules\\AiAgent\\', __DIR__ . DIRECTORY_SEPARATOR . 'src');

/**
 * @var \Symfony\Component\EventDispatcher\EventDispatcherInterface $eventDispatcher Injected by the OpenEMR module loader.
 */
$bootstrap = new Bootstrap($eventDispatcher);
$bootstrap->subscribeToEvents();
