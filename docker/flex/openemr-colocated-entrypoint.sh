#!/bin/bash
#
# Co-located DB entrypoint for the Railway OpenEMR demo.
#
# Starts a local MariaDB inside the app container, then hands off to the stock
# flex entrypoint pointed at 127.0.0.1. This removes the ~3.3 ms cross-service
# network round-trip that dominates chart-load time — a patient chart fires
# ~10k queries, so local (~0.1 ms) vs networked (~3.3 ms) is ~1-2 s vs ~33 s.
# See docs/railway-db-colocation-plan.md.
#
# DATADIR lives on the CONTAINER filesystem (not the volume): the volume is
# mounted under the 0500 apache-owned webroot, which mysql (uid 100) cannot
# traverse, and the flex entrypoint re-hardens webroot perms. Keeping the
# datadir at /var/lib/mysql avoids all of that. Consequence: the database is
# re-seeded from SEED_SQL on every boot (the DB resets to the demo baseline on
# redeploy/restart). True persistence would require remounting the volume
# outside the webroot — tracked as a follow-up.
set -euo pipefail

OE_ROOT="/var/www/localhost/htdocs/openemr"
DATADIR="${OE_DB_DATADIR:-/var/lib/mysql}"
SOCK="/run/mysqld/mysqld.sock"
SEED_SQL="${OE_DB_SEED_SQL:-$OE_ROOT/sites/.db-seed/openemr-seed.sql}"
SQLCONF="$OE_ROOT/sites/default/sqlconf.php"
DB_NAME="${MYSQL_DATABASE:-openemr}"
DB_USER="${MYSQL_USER:-openemr}"
DB_PASS="${MYSQL_PASS:-openemr}"
DB_ROOT_PASS="${MYSQL_ROOT_PASS:-root}"
BUFFER_POOL="${OE_DB_BUFFER_POOL:-1536M}"

log() { echo "[colo-db] $*"; }
sql() { mariadb --protocol=socket --host=localhost --socket="$SOCK" "$@"; }

mkdir -p /run/mysqld "$DATADIR"
chown mysql:mysql /run/mysqld "$DATADIR"

# CUTOVER-#3 POSTMORTEM: never infer "fresh install" from the datadir path
# existing — the image build (apk/base layers) pre-creates an initialized
# $DATADIR/mysql, so a `[ ! -d ... ]` check silently skipped provisioning AND
# the seed import, and the app served an empty database. Instead: detect
# system-table presence by file, and gate provisioning/seeding on the actual
# contents of the running server (below).
if [ -z "$(find "$DATADIR/mysql" -maxdepth 1 \( -name 'global_priv.*' -o -name 'user.MYD' \) -print -quit 2>/dev/null)" ]; then
    log "no system tables found — (re)initializing MariaDB datadir at $DATADIR"
    find "$DATADIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    mariadb-install-db --user=mysql --datadir="$DATADIR" \
        --auth-root-authentication-method=normal --skip-test-db >/dev/null
fi

log "starting mariadbd (buffer pool $BUFFER_POOL)"
# --skip-networking=0 is REQUIRED: Alpine's mariadb-server.cnf ships with
# skip-networking enabled, which would leave mariadbd socket-only (port 0).
# OpenEMR's mysqli connects over TCP to 127.0.0.1:3306, so TCP must be bound;
# without it the connection fails and OpenEMR's retry path exhausts PHP memory.
# --max-prepared-stmt-count raised far above the default 16382: OpenEMR uses
# persistent connections and a chart fires ~8-10 concurrent fragment requests,
# each preparing thousands of statements. Against a fast local DB these are all
# live at once and blow the default limit ("SQL Statement failed on preparation"
# -> Monolog then exhausts PHP memory formatting the error). The slow remote DB
# never hit this because prepares were spread over ~33s. Validated on the
# throwaway service: 60 concurrent authenticated chart loads, all 200, no
# prepare failures.
setsid sh -c "mariadbd --user=mysql --datadir='$DATADIR' --socket='$SOCK' \
    --skip-networking=0 --bind-address=127.0.0.1 --port='${MYSQL_PORT:-3306}' \
    --max-prepared-stmt-count=4194304 \
    --innodb-buffer-pool-size='$BUFFER_POOL' >/var/log/mariadbd.log 2>&1" </dev/null >/dev/null 2>&1 &

for _ in $(seq 1 90); do
    if mariadb-admin --protocol=socket --socket="$SOCK" ping >/dev/null 2>&1; then break; fi
    sleep 1
done
mariadb-admin --protocol=socket --socket="$SOCK" ping >/dev/null 2>&1 \
    || { log "mariadbd failed to start"; tail -20 /var/log/mariadbd.log || true; exit 1; }
# Confirm TCP is actually bound before handing off (fail fast if the config
# still forced socket-only).
if ! netstat -ltn 2>/dev/null | grep -q "127.0.0.1:${MYSQL_PORT:-3306}"; then
    log "WARNING: mariadbd not listening on TCP 127.0.0.1:${MYSQL_PORT:-3306} — OpenEMR (mysqli/TCP) will fail"
fi

# Root auth depends on which path initialized the datadir: passwordless right
# after mariadb-install-db, DB_ROOT_PASS once provisioning below has run.
if ! sql -u root -e 'SELECT 1' >/dev/null 2>&1; then
    export MYSQL_PWD="$DB_ROOT_PASS"
    sql -u root -e 'SELECT 1' >/dev/null 2>&1 \
        || { log "FATAL: cannot authenticate to local mariadbd as root"; exit 1; }
fi

# Idempotent every boot — CREATE IF NOT EXISTS throughout, so this is safe to
# run regardless of how the datadir came to exist.
log "provisioning database, users and grants"
sql -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS '${DB_USER}'@'127.0.0.1' IDENTIFIED BY '${DB_PASS}';
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
ALTER USER 'root'@'localhost' IDENTIFIED BY '${DB_ROOT_PASS}';
CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '${DB_ROOT_PASS}';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL
# Root now has a password (ALTER USER above) — all further client calls use it.
export MYSQL_PWD="$DB_ROOT_PASS"

# Seed only when the openemr schema is actually empty — the ground truth, not a
# filesystem heuristic. table_count query doubles as a connectivity check.
table_count() {
    sql -u root -N -B -e \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}'"
}
TABLES_BEFORE="$(table_count)"
if [ "$TABLES_BEFORE" -eq 0 ]; then
    # Validation/throwaway convenience: if no seed file exists but a source host
    # is given, dump it from that remote MySQL first (self-seeding, no baked dump).
    if [ ! -f "$SEED_SQL" ] && [ -n "${OE_DB_SEED_FROM_HOST:-}" ]; then
        log "no local seed; dumping from remote ${OE_DB_SEED_FROM_HOST} to seed the local DB"
        mkdir -p "$(dirname "$SEED_SQL")"
        MYSQL_PWD="${OE_DB_SEED_FROM_PASS:-$DB_ROOT_PASS}" mariadb-dump --ssl-verify-server-cert=0 \
            -h "$OE_DB_SEED_FROM_HOST" -P "${OE_DB_SEED_FROM_PORT:-3306}" \
            -u "${OE_DB_SEED_FROM_USER:-root}" \
            --single-transaction --routines --triggers --no-tablespaces "$DB_NAME" \
            > "$SEED_SQL" 2>/var/log/seed-dump.log \
            || { log "remote seed dump failed"; tail -3 /var/log/seed-dump.log || true; }
    fi
    if [ -f "$SEED_SQL" ]; then
        log "importing seed dump ($(du -h "$SEED_SQL" | cut -f1)) from $SEED_SQL"
        sql -u root "${DB_NAME}" < "$SEED_SQL"
        log "seed import complete"
    else
        log "no seed dump at $SEED_SQL — the stock entrypoint will run OpenEMR setup"
    fi
fi

# HARD GATE before serving traffic: if this site expects data — a seed exists,
# a seed source is configured, or sqlconf says the site is already configured —
# the schema must be populated with the OpenEMR sentinel tables, and the app DB
# user must be able to read them over TCP exactly as mysqli will. Exiting
# non-zero here fails the deployment (Railway keeps the previous deployment
# serving) instead of ever exposing an empty demo again. The only path that
# skips the gate is a genuinely unconfigured site (fresh install about to run).
SITE_CONFIGURED=0
[ -f "$SQLCONF" ] && grep -qE '\$config\s*=\s*1' "$SQLCONF" && SITE_CONFIGURED=1
if [ "$SITE_CONFIGURED" = "1" ] || [ -f "$SEED_SQL" ] || [ -n "${OE_DB_SEED_FROM_HOST:-}" ]; then
    TABLES_AFTER="$(table_count)"
    USERS_ROWS="$(sql -u root -N -B -e "SELECT COUNT(*) FROM \`${DB_NAME}\`.users" 2>/dev/null || echo 0)"
    PATIENT_ROWS="$(sql -u root -N -B -e "SELECT COUNT(*) FROM \`${DB_NAME}\`.patient_data" 2>/dev/null || echo 0)"
    log "verify: tables=${TABLES_AFTER} users=${USERS_ROWS} patients=${PATIENT_ROWS}"
    if [ "$TABLES_AFTER" -lt 100 ] || [ "$USERS_ROWS" -lt 1 ] || [ "$PATIENT_ROWS" -lt 1 ]; then
        log "FATAL: seed verification failed — refusing to serve an empty/partial database"
        exit 1
    fi
    if ! MYSQL_PWD="$DB_PASS" mariadb --protocol=tcp -h 127.0.0.1 -P "${MYSQL_PORT:-3306}" \
            -u "$DB_USER" -N -B -e "SELECT 1 FROM \`${DB_NAME}\`.users LIMIT 1" >/dev/null 2>&1; then
        log "FATAL: app user '${DB_USER}' cannot read ${DB_NAME} over TCP 127.0.0.1 — refusing to serve"
        exit 1
    fi
fi

# Point the persisted sqlconf at the local server (it was configured for the
# remote MySQL service). Only $host changes; user/pass/db are preserved.
if [ -f "$SQLCONF" ]; then
    if grep -qE "\\\$host\s*=" "$SQLCONF"; then
        sed -i -E "s/(\\\$host\s*=\s*)'[^']*'/\1'127.0.0.1'/" "$SQLCONF"
        log "sqlconf \$host set to 127.0.0.1"
    fi
fi

unset MYSQL_PWD
export MYSQL_HOST=127.0.0.1
log "handing off to stock openemr.sh"
exec "$OE_ROOT.sh" "$@"
