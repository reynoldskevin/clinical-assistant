<?php

/**
 * T53a — create the `ai_derived_fact` provenance table.
 *
 * One row per clinical record the AI persist step files into the chart, tracing
 * it back to the source document + extraction run so a re-extracted document can
 * supersede the prior run's derived records rather than duplicating them.
 *
 * @package   openemr
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Core\Migrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\DBAL\Schema\Table;
use Doctrine\DBAL\Types\Types;
use Doctrine\Migrations\AbstractMigration;

final class Version20260717020718 extends AbstractMigration
{
    use CreateTableTrait;

    public function getDescription(): string
    {
        return 'Create ai_derived_fact provenance table (T53 derived-fact supersede-by-run)';
    }

    public function up(Schema $schema): void
    {
        $table = new Table('ai_derived_fact');

        $table->addColumn('id', Types::BIGINT, ['autoincrement' => true, 'unsigned' => true]);
        $table->addColumn('uuid', Types::BINARY, ['length' => 16, 'notnull' => true, 'fixed' => true]);
        $table->addColumn('pid', Types::INTEGER, ['notnull' => true]);
        $table->addColumn('source_document_id', Types::INTEGER, ['notnull' => true]);
        $table->addColumn('extraction_run_id', Types::STRING, ['length' => 64, 'notnull' => true]);
        $table->addColumn('doc_type', Types::STRING, ['length' => 31, 'notnull' => true]);
        $table->addColumn('fact_type', Types::STRING, ['length' => 31, 'notnull' => true]);
        $table->addColumn('target_table', Types::STRING, ['length' => 64, 'notnull' => true]);
        $table->addColumn('target_id', Types::BIGINT, ['notnull' => true]);
        $table->addColumn('target_uuid', Types::BINARY, ['length' => 16, 'notnull' => false, 'fixed' => true]);
        $table->addColumn('fact_summary', Types::STRING, ['length' => 255, 'notnull' => true]);
        $table->addColumn('created_by', Types::INTEGER, ['notnull' => true]);
        $table->addColumn('created_at', Types::DATETIME_MUTABLE, ['notnull' => true]);
        $table->addColumn('superseded_at', Types::DATETIME_MUTABLE, ['notnull' => false]);
        $table->addColumn('active', Types::SMALLINT, ['notnull' => true, 'default' => 1]);

        $this->addPrimaryKey($table, 'id');
        $table->addIndex(['pid', 'source_document_id', 'fact_type'], 'idx_ai_derived_fact_scope');
        $table->addIndex(['extraction_run_id'], 'idx_ai_derived_fact_run');

        $this->createTable($table);
    }

    public function down(Schema $schema): void
    {
        $this->addSql('DROP TABLE ai_derived_fact');
    }
}
