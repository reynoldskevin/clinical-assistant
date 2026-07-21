# Railway DB Co-location Plan

Migrate the Railway OpenEMR demo (`soothing-appreciation` / `truthful-peace`)
from a **separate networked MySQL service** to a **MariaDB co-located inside the
app container** (local Unix/loopback socket).

## Why

Loading a patient chart fires **~27,000 MySQL queries** (measured via the
slow log). Each query is sub-millisecond on the server, but each is a separate
**~3.3 ms round-trip** across Railway's private-network overlay to the MySQL
service. ~10,000 of those run inside `demographics.php` →
`10,000 × 3.3 ms ≈ 33 s`. The 3.3 ms is inherent to cross-service private
networking (verified: not TLS, not tunable).

Query anatomy for one chart load:

| Category | Queries | Share |
|---|---:|---:|
| `PREPARE` + `CLOSE STMT` (3 round-trips/query) | 12,435 | 45% |
| Audit logging (`log` + `log_comment_encrypt`) | 5,294 | 19% |
| Translation N+1 (`lang_definitions`) | 2,622 | 10% |
| Schema introspection (`SHOW TABLES/COLUMNS`) | 1,453 | 5% |
| ACL checks (`gacl_acl`) | ~1,000 | 4% |
| Actual patient data (N+1-inflated) | 7,540 | 28% |

OpenEMR is designed for a **local** database (~0.05 ms/query on a socket); the
same page renders in ~1–2 s locally. Co-locating the DB removes the network
multiplier: **~33 s → ~1–2 s**.

Ruled out first (with evidence): OPcache/compilation (cold==warm), the AI
Co-Pilot module (no server-side call on render), app CPU (workers never in
running state — always I/O wait), and external hangs/DNS (the only foreign peer
during the stall is MySQL:3306).

## Bonus

OpenEMR local dev already runs on MariaDB. Co-locating on MariaDB aligns prod
with dev and eliminates the "MySQL-9-strict vs local-MariaDB dialect drift"
bug class.

## Facts (measured)

- DB: **284 InnoDB tables, 235 MB** — trivial to dump/import.
- MariaDB-compatible: **0** `utf8mb4_0900` collations, **0** JSON columns
  (the two classic MySQL-9→MariaDB import breakers). 77 generated columns, all
  part of OpenEMR's natively-MariaDB-supported schema.
- Base image (`openemr/openemr:flex`, Alpine v3.23) has **`mariadb-11.4`** in
  its repo.
- `sites` volume: 45 GB, 6.4 MB used — room to also hold the DB datadir.
- Flex entrypoint honors `MYSQL_HOST` and already waits-for-DB.

## Constraints that shape the design

- Railway = **one volume per service** and **one container per service**. So the
  DB must run *inside* the app container, with its datadir on the *existing*
  `sites` volume, and both `mariadbd` + Apache run under one entrypoint.

## Plan

### Stage 0 — Prep & safety (no prod impact)
- `mysqldump --single-transaction --routines --triggers openemr > openemr.sql`
  (~235 MB, seconds).
- Keep the separate MySQL service running as the rollback target throughout.

### Stage 1 — Build the combined image (de-risk the import first)
- `Dockerfile.railway`: `FROM openemr/openemr:flex` +
  `apk add --no-cache mariadb mariadb-client` + a startup wrapper.
- Wrapper (`docker/flex/openemr-colocated-entrypoint.sh`), run before the stock
  `openemr.sh`:
  1. If datadir empty → `mariadb-install-db`, start `mariadbd`, import the seed
     dump once.
  2. Else → start `mariadbd`, wait for socket.
  3. `exec` the stock `openemr.sh` with `MYSQL_HOST=127.0.0.1`.
- Keep the OPcache ini added earlier.
- `innodb-buffer-pool-size ≈ 1.5 GB` (DB is 235 MB; app + DB share 4 GB/4 vCPU).
- **Validate the MySQL-9 → MariaDB-11.4 import in a throwaway container before
  any cutover** (this is the main dialect risk).

### Stage 2 — Config
- The wrapper exports `MYSQL_HOST=127.0.0.1` and rewrites the persisted
  `sqlconf.php` `$host` to `127.0.0.1`, so no service env change is required.
- **Datadir location — decided: container fs `/var/lib/mysql` (ephemeral), NOT
  the volume.** The volume mounts under the webroot `.../openemr`, which is
  `0500` and owned by uid 1000 (apache); `mysql` (uid 100) cannot even traverse
  it, and `openemr.sh` re-hardens webroot perms to `500/400`. Putting the
  datadir on the container fs sidesteps all of this.
  - **Consequence:** the DB is re-seeded from the volume dump on every boot, so
    it resets to the demo baseline on redeploy/restart. Acceptable for a
    synthetic, read-only-agent demo.
  - **True persistence (follow-up):** remount the single volume *outside* the
    webroot (e.g. `/oedata`), place both `sites/` and the DB datadir under it,
    and symlink `.../openemr/sites -> /oedata/sites`. Deferred to keep the
    cutover low-risk.
- Seed dump lives on the persistent volume at `sites/.db-seed/openemr-seed.sql`
  (refresh it by re-dumping to update the demo baseline).

### Stage 3 — Cutover
- Deploy the combined image with imported data. Load a chart; re-run the
  slow-log / `/proc` checks to confirm queries are now local and the page is
  ~1–2 s.

### Stage 4 — Decommission & durability
- After a verification window, delete the separate MySQL service.
- DB now lives on the app volume → ensure Railway volume backups are on. A
  redeploy briefly restarts the DB (acceptable for a demo).

## Risks (all low / manageable)

- **MySQL 9 → MariaDB dialect:** low — no JSON / 0900 collations; OpenEMR
  supports MariaDB natively; 235 MB import is easy to test in a throwaway before
  cutover (Stage 1).
- **App + DB share 4 vCPU:** removing the 3.3 ms×~10k latency vastly outweighs
  shared CPU; bump vCPU if needed.
- **Two processes per container:** standard pattern; the wrapper owns
  start-order and the one-time import.

## Stage 1 validation results (throwaway import test — PASSED)

Ran a real `mysqldump`(prod MySQL 9.4) → import(throwaway MariaDB 11.4) inside
the app container, datadir on the container fs, socket-only (verified never
touches prod):

- Dump: 194 MB; **zero `utf8mb4_0900` references** (no unknown-collation break).
- Import: **0 errors**, clean exit.
- Data parity exact: tables 284=284; `lang_definitions` 237,509=237,509,
  `forms` 6,350=6,350, `list_options` 5,605=5,605, `patient_data` 21=21, etc.
  (`log` differed by ~13 rows only because prod's audit log grew during the
  dump). Sample query returned patient 1 = `Brett333 Cruickshank494` (Synthea
  synthetic data — no real PHI).
- Apparent `generated columns src=77 dst=0` is a **false alarm**: all 77 are
  `DEFAULT CURRENT_TIMESTAMP` / `ON UPDATE CURRENT_TIMESTAMP` columns (MySQL 8+
  labels these `DEFAULT_GENERATED` in `information_schema`; the generation
  expression is empty). MariaDB supports them identically, just labels them
  differently. No data-fidelity loss.

Conclusion: the dump→MariaDB migration is safe. `mariadb-dump` from the MySQL 9
server preserves schema + data faithfully.

Artifacts authored this stage (not yet the live deploy target):
- `Dockerfile.railway.colocated` — flex + bundled MariaDB + wrapper ENTRYPOINT.
- `docker/flex/openemr-colocated-entrypoint.sh` — starts local mariadbd
  (datadir on the sites volume, chowned + seeded once from the dump) then execs
  the stock `openemr.sh` against `127.0.0.1`.

Open item for Stage 2/3 (not a blocker): mariadbd could not init on the
*volume-mounted* datadir in a bare test due to volume ownership; the image
entrypoint runs as root and `chown`s the datadir before init/start, which
resolves it — to be confirmed on the first real deploy.

## Cutover attempt #1 — failed, rolled back, root-caused

First cutover 500'd. Two issues found:

1. **`skip-networking` (fixed):** Alpine's `mariadb-server.cnf` ships with
   `skip-networking` enabled, so `mariadbd` ran socket-only (`port: 0`) and
   ignored `--bind-address/--port`. OpenEMR's mysqli connects over **TCP** to
   `127.0.0.1:3306` → refused. Fix: pass **`--skip-networking=0`** on the
   `mariadbd` command line (now in the entrypoint, with a post-start TCP check).
2. **512 MB PHP memory exhaustion (not a real issue):** appeared only as
   *fallout* of the failed connection — OpenEMR's connection retry / error path
   under the fork's `ADODB_mysqli_log` wrapper accumulates memory when mysqli
   returns false. With a working connection it does not occur.

**Off-prod validation (green):** started a throwaway local MariaDB with
`--skip-networking=0` (TCP `127.0.0.1:3306`) seeded from the volume dump, then
created a **second OpenEMR site** whose `sqlconf` pointed at it and hit its login
through OpenEMR's real code path. Result: **`http=200` in 77 ms, no memory
error**, `openemr` TCP auth OK, 284 tables. Confirms `--skip-networking=0` +
`sqlconf host=127.0.0.1` is the complete fix. The live `default` site was
untouched throughout.

### ⚠️ Operational gotcha — `sqlconf.php` is on the volume

`sites/default/sqlconf.php` persists on the volume, so the colocated entrypoint's
`$host` rewrite to `127.0.0.1` **survives a rollback**. The stock networked
`openemr.sh` does NOT reset `$host`, so after a rollback the networked image
reads `127.0.0.1`, finds no local DB, and 500s. **Rollback must also reset**
`$host` back to `mysql.railway.internal` (sed the file; OPcache picks it up
within `revalidate_freq`=60 s, or redeploy for an immediate fresh cache).

## Cutover attempt #2 — booted & connected, but heavy pages crashed; rolled back

With `--skip-networking=0`, the colocated deploy came up green: TCP bound,
`sqlconf host=127.0.0.1`, DB connections on loopback, **login 200**, loopback
latency **0.037 ms** (vs 3.3 ms remote, ~89×). But when a real (heavy) page was
loaded, the app spewed:
`SQL Statement failed on preparation: SELECT lang_definitions.definition ...`
and `PHP Fatal error: Allowed memory size exhausted in monolog/.../LineFormatter.php`.

**Root cause (found in code):** `src/BC/DatabaseConnectionFactory.php` uses
**persistent connections** (`PConnect` / `p:host`). A chart fires ~8–10
concurrent fragment requests, each preparing thousands of statements. Against a
*fast* local DB they are all live simultaneously and exhaust MariaDB's default
**`max_prepared_stmt_count` (16382)** → prepares fail → OpenEMR logs each
failure and **Monolog's `LineFormatter` exhausts the 512 MB PHP limit** formatting
it. The slow remote DB never hit this because prepares were spread over ~33 s
(few live at once). **The latency fix is what exposed this latent bug.**

**Candidate fix (in the entrypoint, NOT yet validated):**
`--max-prepared-stmt-count=4194304` on `mariadbd`.

**Validation gap:** attempt #2 was only validated against *login* (few queries),
which missed this. Attempt #3 must reproduce a **concurrent, authenticated heavy
page** (dashboard/chart) off-prod — ideally on a throwaway Railway service, not
the live demo — before any cutover.

## Cutover attempt #3 — served an EMPTY database; rolled back

The `--max-prepared-stmt-count` fix held, but the app came up with an empty
`openemr` schema: the entrypoint gated *provisioning and seed import* on
`[ ! -d "$DATADIR/mysql" ]`, and the image build pre-creates an initialized
`/var/lib/mysql/mysql` — so the "fresh datadir" branch never ran. Nothing
failed loudly; the deploy looked green and served a broken demo.

**Fix (implemented 2026-07-21 in `openemr-colocated-entrypoint.sh`):**

1. **No filesystem heuristics.** Datadir init is detected by system-table
   files (`mysql/global_priv.*`); provisioning is idempotent and runs every
   boot; the seed import is gated on the *actual* table count of the running
   server (`information_schema.tables`), not on how the datadir looked.
2. **Hard verification gate before serving.** If the site expects data (seed
   file present, seed source configured, or `sqlconf.php` says configured),
   the entrypoint requires ≥100 tables, ≥1 user, ≥1 patient, and a successful
   read as the app DB user over TCP 127.0.0.1 — otherwise it `exit 1`s and
   never starts Apache.
3. **Railway healthcheck** (`railway.json` → `healthcheckPath` on the login
   page, 900 s timeout). Combined with (2), a failed cutover deployment now
   **fails during rollout while the previous deployment keeps serving** — the
   empty-demo outage mode of attempt #3 is structurally impossible.

## Validation matrix before cutover #4 (all on throwaway `oe-colo-test`)

The throwaway previously had **no volume** — which is why validation kept
exercising the fresh-install path instead of the live path. It now has a
volume at the same mount point as prod (`.../openemr/sites`).

- **T1** fresh volume, no seed → fresh install works; writes `sqlconf.php`
  (recreates prod preconditions).
- **T2** `OE_DB_SEED_FROM_HOST` self-seed from prod MySQL (read-only dump) →
  import + verification gates pass; login with prod creds; chart shows data.
- **T3** redeploy with seed file now ON the volume → **the exact live path**
  (pre-initialized datadir + configured sqlconf + on-volume seed) — the path
  attempt #3 failed on.
- **T4** concurrent burst (20×3 chart loads) → no prepared-stmt exhaustion.
- **T5** failure drill: break the seed deliberately → deployment must FAIL
  (gate + healthcheck) while the previous deployment keeps serving.

Cutover #4 proceeds only if T1–T5 all pass.

### Results (2026-07-21) — matrix complete

- **T1** — *superseded*: adding the volume auto-redeployed the old image,
  which wrote a configured `sqlconf.php` to the fresh volume; the new gate
  then (correctly) crash-looped rather than serve "configured but empty".
  Fresh-install path is irrelevant to cutover; skipped.
- **T2 — PASSED.** Self-seed dump from prod MySQL 9.4 (read-only,
  `--single-transaction`) wrote a 197 MB seed to the volume; imported into
  local MariaDB 11.4 with zero dialect/collation errors.
- **T3 — PASSED (×2 boots).** The exact live path — pre-initialized datadir
  + configured sqlconf + on-volume seed — re-inits, imports in ~20 s,
  verifies `tables=284 users=4 patients=21`, then serves. Repeatable.
- **T4 — PASSED.** 60 authenticated chart loads at 20-way concurrency:
  zero 5xx, zero prepared-statement failures (peak 59 DB connections);
  overload just queues. Sequential charts: **1.4–5 s** (vs ~33 s networked).
- **T5 — PASSED with a caveat.** Broken seed → FATAL gate → deployment
  FAILED; the broken build never served. **Caveat discovered: services with
  volumes get no overlapping deploys on Railway** — the old container stops
  when the rollout starts, and after a FAILED deploy the service stays DOWN
  (no auto-restore of the previous deployment). So the gate guarantees
  *never serving a broken/empty app*, but NOT zero-downtime:
  - successful cutover ≈ one boot of downtime (~20 min: runtime app build
    + dump/import);
  - failed cutover ≈ downtime until manual rollback (revert image /
    redeploy last-good ≈ 5–10 min).
  Cutover #4 should therefore be run in an agreed window, with the rollback
  command pre-staged.

Also required on the live service before cutover #4: **`PORT=80`** (the
Railway healthcheck cannot find the probe port otherwise — it never
connects, and deploys sit in DEPLOYING until the 2700 s timeout, then FAIL).

Operational learnings from the validation runs (2026-07-21):

- **`railway.json` `dockerfilePath` beats the `RAILWAY_DOCKERFILE_PATH`
  service variable.** The var is still set on `oe-colo-test` but does
  nothing. Throwaway deploys are done by flipping `railway.json` locally
  (uncommitted) for the `railway up`, then flipping back.
- **First boot of the flex image takes ~20 min** (clone + composer + npm at
  container start), and a cutover boot adds the 194 MB seed import. The
  Railway `healthcheckTimeout` is set to 2700 s to cover this; 900 s caused a
  false FAILED. Corollary for cutover: the old deployment keeps serving
  through the whole ~20 min rollout, so the cutover itself is zero-downtime
  if the healthcheck gate holds (T5 verifies).

## Rollback

Until the separate MySQL service is deleted, revert by setting `MYSQL_HOST` back
to `mysql.railway.internal` and redeploying the previous image.
