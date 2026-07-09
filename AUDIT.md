# OpenEMR Audit Summary

The application's architecture and code are fundamentally sound — access control fails closed, queries are parameterized, output is escaped, crypto primitives are strong. The material risks live in data-handling posture, the runtime execution model, and data integrity — and these, not the code, are what constrain the planned AI chart-querying agent.

Security (most impactful). A focused review found and fixed 10 real defects — a FHIR Person IDOR exposing any record to a patient token, an MFA bypass, and a SQL injection among them (all committed on a branch). But the dominant risks are architectural: PHI is stored plaintext at rest (field-level encryption covers only secrets), and the audit log is not tamper-evident (an unkeyed hash co-located with the data). Both recur as compliance failures.

Performance. A large, uncached per-request "tax" dominates latency — every request reloads the ~800-row globals table, runs an uncached ACL/menu JOIN storm, and writes a synchronous audit row. A single FHIR read is ~80–90% fixed overhead before any data. Most decisively, the synchronous PHP-FPM model imposes a hard ~60s ceiling, no async, no streaming, and no job queue — meaning areal-time agent calling an external LLM cannot live in the request path; it must run as an external streaming sidecar.

Architecture. Three code generations (legacy procedural, Laminas modules, modern PSR-4) coexist behind one Symfony EventDispatcher, which is the clean extension seam. The agent's natural shape: a custom module for the in-EHR UI plus a batched read endpoint, with LLM orchestration in the sidecar.

Data quality. The schema has zero foreign keys and no natural-key uniqueness on patients — duplicate patients and orphan records are structurally possible, and the pervasive NOT NULL DEFAULT'' convention makes "missing" indistinguishable from "blank." Profiling OpenEMR's own demo data proved these aren't theoretical: 29% of patients missing sex (a "required" field), 100% missingrace/ethnicity, a duplicate SSN, and 100% unregistered UUIDs. A fresh install also ships empty ICD/CPT/SNOMED/RxNorm vocabularies — clinical codes are absent until separately loaded.

Compliance. The breach-notification posture is the sharpest gap: because audit logging attributes reads to the session rather than the record accessed, you cannot reliably enumerate whose PHI a compromised account touched — the core §164.404 requirement — and with PHI unencrypted at rest there is no breach safe-harbor. There is also no retention or disposal engine (deleting adocument never removes the file from disk). Sending PHI to the LLM makes the provider a Business Associate requiring a BAA (Anthropic offers one for the Claude API + zero data retention).

The single most important cross-cutting decision: compliance and performance point opposite ways on the agent's data path. The fastest option (direct DB reads) produces zero audit trail and is a compliance non-starter for real PHI; the compliant option is an audited API/service boundary with the agent as a distinct logged principal. That tension — resolved toward the audited path for real PHI, with a synthetic-data demo carve-out — should anchor the agent's design.


--------------------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------------------


# Security Audit

## Severity summary

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| C1 | Critical | Bulk clinical PHI plaintext at rest in MySQL | `src/Common/Crypto/CryptoGen.php:65` |
| C2 | Critical | Container filesystem without a persistent volume wipes PHI documents *and* drive encryption keys | `docker/flex/Dockerfile:216` |
| C3 | Critical | Audit log not tamper-evident (unkeyed checksums) | `src/Common/Logging/Audit/LogTablesSink.php:63` |
| H1 | High | FHIR `Person/:uuid` IDOR — cross-object PHI read | `apis/routes/_rest_routes_fhir_r4_us_core_3_1_0.inc.php:642` |
| H2 | High | Core web-UI MFA bypassable (no session gate) | `src/Common/Auth/AuthUtils.php:488` |
| H3 | High | SQL injection in eye_mag report | `interface/forms/eye_mag/report.php:2528` |
| H4 | High | Transmission security not enforced by app (Secure cookie + HTTPS redirect) | `src/Common/Session/SessionConfigurationBuilder.php:26`, `docker/flex/openemr.conf:154` |
| H5 | High | OAuth password-grant MFA + confidential-client secret gaps | `src/Common/Auth/OpenIDConnect/Repositories/UserRepository.php:109`, `ClientRepository.php:198` |
| H6 | High | Fax/scan viewer serves PHI with no ACL check | `interface/fax/fax_view.php` |
| M1 | Medium | Brute-force throttle bypassable via `X-Forwarded-For` | `library/sanitize.inc.php:29` |
| M2 | Medium | Reflected XSS via `PHP_SELF`/`SERVER_NAME` | `interface/modules/zend_modules/module/Application/src/Application/Helper/Javascript.php:26` |
| M3 | Medium | ~13 state-changing POST handlers missing CSRF verification | multiple (see below) |
| M4 | Medium | Document IDOR guard bypassable via empty `patient_id` | `controllers/C_Document.class.php:670` |
| M5 | Medium | Core session cookie not `HttpOnly` | `src/Common/Session/SessionConfigurationBuilder.php:83` |
| M6 | Medium | Weak one-time PIN for portal reset | `src/Common/Auth/OneTimeAuth.php:87` |
| M7 | Medium | Billing EDI/ERA PHI written as plaintext files | `interface/billing/sl_eob_search.php:998` |
| L1–L10 | Low | Hardening items (see below) | various |

---

## CRITICAL

### C1 — Bulk clinical PHI is plaintext at rest in MySQL
Field-level DB encryption covers only *secrets* (payment tokens, MFA/OAuth keys,
fax/SMS creds) — **not** `patient_data`, `history_data`, `forms`, encounters, or
notes. CryptoGen's own docblock concedes this (`src/Common/Crypto/CryptoGen.php:65`).
If the underlying MySQL is not itself encrypted at rest, demographics + clinical
data sit unencrypted on disk.
*HIPAA §164.312(a)(2)(iv) encryption / §164.312(c)(1) integrity.*

### C2 — Container filesystem without a persistent volume wipes PHI documents *and* the drive encryption keys
`docker/flex/Dockerfile:216` declares a persistent `VOLUME` only for TLS certs
(`/etc/letsencrypt`, `/etc/ssl`) — **not `sites/`**, where patient documents
(`sites/<site>/documents/`) and the drive key set
(`.../logs_and_misc/methods/`) live. On any container host without a persistent
volume mounted over `sites/`, every redeploy/restart destroys documents *and*
keys. Because DB secrets are encrypted *with* the drive keys, losing `methods/`
permanently orphans the encrypted DB columns too — a mutual key dependency that
turns a storage reset into unrecoverable data loss.
*HIPAA §164.312(c)(1) integrity, §164.308(a)(7) contingency/backup.*

### C3 — Audit log is not tamper-evident
Row checksums are unkeyed `hash('sha3-512', …)` — no HMAC secret, no hash chain
(`src/Common/Logging/Audit/LogTablesSink.php:63`). Anyone with DB write access
can edit a `log` row, recompute the hash, overwrite
`log_comment_encrypt.checksum`, and `interface/reports/audit_log_tamper_report.php`
still reports "clean." Deleting the paired `log` + `log_comment_encrypt` rows
leaves no trace, and `extended_log` (disclosure accounting) has no checksum
column at all. The audit trail is therefore repudiable to anyone holding DB
credentials. *HIPAA §164.312(b) audit controls, §164.312(c)(1) integrity.*
**In-code mitigation:** enabling ATNA TLS-syslog (`enable_atna_audit`, off by
default) ships logs to an off-host repository, materially reducing this.

---

## HIGH

### H1 — FHIR `Person/:uuid` IDOR (cross-object PHI read) — *most cleanly exploitable code defect*
`apis/routes/_rest_routes_fhir_r4_us_core_3_1_0.inc.php:642` — the patient-token
branch calls `getOne($uuid)` with no patient binding and no check (the comment
says binding is required but it is not done). `patient/Person.read` is a
grantable scope and `FhirPersonService` is backed by the `users` table, so a
patient app can read **any user/practitioner or other-patient Person record by
UUID**. Practitioner UUIDs are routinely disclosed to patients via
CareTeam/Encounter references, making staff-PHI disclosure directly reachable.
The sibling `Patient/:uuid` route (line 610) performs the equality check
correctly. **Fix:** reject or bind to `getPatientUUIDString()` in the `else`
branch.

### H2 — Core web-UI MFA is bypassable (no session-level gate)
`src/Common/Auth/AuthUtils.php:488` (`setUserSessionVariables`) sets
`authUser`/`authPass`/`authUserID` the moment the **password** verifies. The
TOTP/U2F challenge runs only afterward in `interface/main/main_screen.php`, and
MFA completion is never recorded as a session gate — the only artifact is a DB
column written but never read back (`main_screen.php:239`). Every page
authenticates via `AuthUtils::authCheckSession()`
(`AuthUtils.php:837`), which validates the session against the DB **without any
MFA check**. An actor with valid credentials can POST login, receive the
already-authenticated cookie, skip the MFA form, and GET PHI pages directly.
Exploitable when MFA is enabled (not default). **Fix:** set a session flag only
after `check()` succeeds and enforce it in `authCheckSession()`.

### H3 — SQL injection in eye_mag report
`interface/forms/eye_mag/report.php:2528`:
```php
$sql = "SELECT * from documents where documents.name like '%" . $filename . "'";
$doc = sqlQuery($sql);   // no binds
```
`$filename` derives from `$_REQUEST['ptid']`/`$_REQUEST['encid']` (lines 61,65),
unescaped. A single quote breaks the string literal → UNION/comment injection.
Authenticated, but this is the **only live SQLi found** across 4,200+ sampled
call sites (everything else is parameterized or whitelist-escaped). **Fix:** use
a bind — `... LIKE ?` with `['%' . $filename]`.

### H4 — Transmission security not enforced by the application
- Core session cookie is **not** `Secure`-flagged. `SessionConfigurationBuilder`
  defaults `cookie_secure => false` (line 26); `forCore()`/`forPortal()` never
  set it true (only OAuth/API sessions do). The clinician cookie can traverse
  plain HTTP.
- HTTP→HTTPS redirect is **commented out by default**
  (`docker/flex/openemr.conf:154`; "By default, HTTP is allowed"). Behind a
  TLS-terminating reverse proxy (TLS at the edge, plain HTTP to the container),
  the app never enforces TLS on its own leg. HSTS *is* set (line 62), but that
  only helps after a first successful HTTPS load.

*HIPAA §164.312(e)(1) transmission security.*

### H5 — OAuth enforcement gaps (only if `oauth_password_grant` / confidential clients are used)
- **MFA skipped in password grant:** `UserRepository.php:109` enforces MFA only
  *if the client sends* `mfa_token`; a required-MFA user whose client omits it
  falls through to `return true`.
- **Confidential-client secret check skipped when omitted:**
  `ClientRepository.php:198` compares the secret only
  `if (!empty($clientSecret) && !empty($client['is_confidential']))` — a `/token`
  request that sends no `client_secret` passes, so a stolen authorization code is
  redeemable without the secret.

### H6 — Fax/scan viewer serves PHI with no ACL check
`interface/fax/fax_view.php` — authentication + CSRF present, but **no ACL
check** anywhere in `interface/fax/`. Any authenticated user of any role can
`readfile()` any document in the HylaFax queues or scanner output directory via
`jid`/`scan`/`file`. Path traversal *is* blocked by `check_file_dir_name`.
Bounded to deployments where the legacy fax/scan feature is configured. **Fix:**
add `aclCheckCore('patients','docs')` (or appropriate category).

---

## MEDIUM

### M1 — Brute-force throttle bypassable via `X-Forwarded-For`
`library/sanitize.inc.php:29` builds the IP-throttling key as
`REMOTE_ADDR . " (" . $_SERVER['HTTP_X_FORWARDED_FOR'] . ")"`. The `ip_tracking`
and `ip_force_block` tables key on this attacker-influenced string
(`AuthUtils.php:1153`), so rotating the forged `X-Forwarded-For` header yields a
fresh row each request — `ip_login_fail_counter` never accumulates and manual IP
blocks are evaded. Relevant behind any reverse proxy or load balancer that sets
`X-Forwarded-For`. The per-username counter (default 20/hr) still bounds
single-account attacks, but cross-account password-spraying from one host is
unthrottled.

### M2 — Reflected XSS via `PHP_SELF`/`SERVER_NAME`
`interface/modules/zend_modules/module/Application/src/Application/Helper/Javascript.php:26`:
```php
$basePath = str_replace("/index.php", "", $_SERVER['PHP_SELF']);
echo 'var basePath = "' . $scheme . $_SERVER['SERVER_NAME'] . $basePath . '";';
```
`PHP_SELF` carries attacker-controllable `PATH_INFO`, echoed unescaped inside an
inline `<script>` string. Renders on authenticated Carecoordination /
Immunization / Syndromicsurveillance / Documents module layouts. **Fix:** wrap
both in `attr_js()`.

### M3 — ~13 state-changing POST handlers missing server-side CSRF verification
All confirmed to write to the DB with no server-side token check (a hidden form
field is not verification). `SameSite=Strict` on the core cookie downgrades
default-config severity to Medium; directly exploitable via same-site XSS.
Highest-impact:
- `interface/orders/orders_results.php:35` & `single_order_results.php:35` — lab
  result **sign-off** (`review_status='reviewed'`).
- `interface/billing/search_payments.php:51` — **DeletePayments** destroys
  `ar_session`/`ar_activity`.
- `interface/forms/fee_sheet/new.php:530` — fee-sheet/charge save.
- `interface/main/calendar/add_edit_event.php:466` — appointment CRUD.
- `interface/billing/ub04_dispose.php:22`, `interface/drugs/dispense_drug.php`.
- `interface/main/messages/save.php:50` — writes a global setting + starts a
  background service (admin victim).
- `interface/forms/LBF/new.php:227` — LBF clinical data save.
- Lower/optional: `interface/forms/track_anything/create.php:46` (also **no ACL
  check**), `interface/forms/eye_mag/*`.

**Fix:** add `CsrfUtils::checkCsrfInput(INPUT_POST, dieOnFail: true)` in each
save branch.

### M4 — Document IDOR guard bypassable via empty `patient_id`
`controllers/C_Document.class.php:670` — the per-patient IDOR check runs only
`if ($patient_id !== null)`, and `Controller::dispatch()` coerces empty query
values to `null`, so `controller.php?document&retrieve&patient_id=&document_id=<victim>`
skips it, leaving only the (non-per-patient) category ACL. **Fix:** require a
non-null `patient_id` or resolve the pid from the document.

### M5 — Core session cookie not `HttpOnly`
`src/Common/Session/SessionConfigurationBuilder.php:83` (`forCore`) sets
`setCookieHttpOnly(false)` — documented as required for the multi-login
`restoreSession()` JS, but it means any XSS in the authenticated app can read the
`OpenEMR` session cookie directly. Portal/OAuth/API sessions correctly set it
true.

### M6 — Weak one-time PIN for portal reset/registration
`src/Common/Auth/OneTimeAuth.php:87`:
```php
$pin = substr(str_shuffle(str_shuffle("0123456789")), 0, 6);
```
`str_shuffle` uses non-cryptographic Mersenne Twister, and permuting
`"0123456789"` yields 6 **non-repeating** digits — keyspace ~151,200 (10P6),
predictable. The check is loose/non-constant-time
(`processOnetime`) and `enforce_onetime_use`/`max_access_count` are never
enforced, so the "one-time" token is reusable within its 15-min TTL. **Fix:**
`random_int` for the PIN, `hash_equals` for the compare, enforce single use.

### M7 — Billing EDI/ERA PHI written as plaintext files
X12 837/835 claim/remittance files (full patient + claim PHI) are written as raw
files under `documents/edi/`, `documents/era/` regardless of `drive_encryption`
(`interface/billing/sl_eob_search.php:998`, `get_claim_file.php:80`,
`ub04_dispose.php:125`) — same on-disk plaintext exposure as C2.

---

## ⚠️ Compounding chain worth calling out

**M5 (cookie not HttpOnly) + M2 (reflected XSS) + M3 (missing CSRF)** form a real
chain: a single XSS primitive both steals the session cookie *and* drives
same-origin state-changing requests that `SameSite=Strict` cannot stop (it is
same-site). **Fixing M2 (the XSS) is the highest-leverage single action** in this
group.

Separately, **M1 (XFF throttle bypass)** applies whenever the app runs behind a
reverse proxy that sets `X-Forwarded-For`.

---

## LOW (hardening)

- **L1** — OAuth authorization codes not single-use (`AuthCodeRepository.php:21`);
  bounded by 1-min TTL + PKCE.
- **L2** — Reversed prefix check in API auth-skip strategy
  (`SkipAuthorizationStrategy.php:56` — `str_starts_with` args reversed); latent,
  no sensitive route reachable today.
- **L3** — Legacy cost-5 bcrypt hashes still accepted for never-logged-in
  accounts (`AuthHash.php:216`); rehashed on next login.
- **L4** — `admin/acl` can add users to `Administrators` without the
  `admin/super` guard its sibling has (`library/ajax/adminacl_ajax.php:72`).
- **L5** — SSRF allowlist applied inconsistently in SignalWire fax client
  (`SignalWireClient.php:935` unguarded vs `:978` guarded).
- **L6** — `MYSQL_ROOT_PASSWORD: root` in the **production** compose template
  (`docker/production/docker-compose.yml:13`).
- **L7** — Verbose `$e->getMessage()` / `print_r` echoed raw in a few handlers
  (`interface/forms/newpatient/common.php:52`, `interface/forms/eye_mag/save.php:1316`).
- **L8** — Encryption keys co-located with the data they protect
  (`sites/<site>/documents/logs_and_misc/methods/` + same MySQL) — at-rest
  encryption defends only against raw disk/file theft, not full-env compromise.
- **L9** — Docker flex image ships `admin`/`pass`
  (`docker/flex/auto_configure.php:63`); dev default, critical only if that image
  reaches production.
- **L10** — Idle timeout default 7200s (`library/globals.inc.php:2113`); long for
  a clinical workstation under §164.312(a)(2)(iii). Server-side enforcement is
  correct (`SessionTracker.php:58`); recommend lowering the default.

---

## Verified strong (no action needed)

- **SQLi:** core query API (`library/sql.inc.php`) fully parameterized via ADODB
  binds; dynamic identifiers via whitelist helpers (`escape_identifier`,
  `escape_sort_order`, `escape_sql_column_name`). 4,200+ call sites sampled.
- **XSS:** near-universal `text()`/`attr()`/`js_escape()` output escaping; zero
  Smarty `nofilter`; the 31 Twig `|raw` uses are server-built HTML escaped at
  source.
- **File upload/LFI:** MIME whitelist (`isWhiteFile`, default on), encrypted
  UUID-named storage outside webroot (`Document.class.php:1073`), uniform
  filename sanitizers at every include/fopen/readfile sink; no arbitrary
  file-download endpoint.
- **Authorization:** ACL fails closed (`AclMain::aclCheckCore():166`); privilege
  derives from server-set `authUser` re-validated per request; mandatory
  unskippable REST/FHIR scope gate; multisite isolation destroys session on
  `?site=` mismatch.
- **Crypto:** AES-256-CBC + HMAC-SHA384, key versioning, HMAC-authenticated
  decryption (`CryptoGen.php`).
- **Auth:** bcrypt cost-10 / Argon2 defaults; min length 9, strong-password +
  5-password history + 180-day expiry on by default; timing-attack defenses with
  persisted dummy hash; session-fixation migration on login; CSPRNG tokens;
  per-username lockout.
- **OAuth:** PKCE `S256`-only (`plain` rejected); RFC 7523 JWT assertion blocks
  `alg=none`; bearer path independently checks signature + DB revocation +
  expiry + scope; redirect URIs exact-match; RSA-2048 with encrypted private key.
- **Info disclosure:** `phpinfo` env-gated; `display_errors` behind admin debug
  level (default 0); no exposed `.sql`/`.log`/backup under webroot; no production
  secrets committed.
- **HIPAA positives:** server-side idle logoff; document dir denied direct HTTP
  access; HSTS + TLS1.2/1.3-only + security headers in flex conf; disclosure
  accounting feature exists; ATNA remote-audit support available.

### Important by-design caveat

OpenEMR has **no per-patient object-level authorization** in the web UI —
category ACLs (e.g. `patients/demo`) gate *what data types* a role sees, never
*which patient*. `pt_restrict_field` is search-only (`library/patient.inc.php:564`).
Do not treat either as a facility/care-team isolation boundary. This is the
documented model, not a bug, but it shapes the threat model.

---

## Recommended remediation order

**Application code (highest priority — bugs regardless of configuration):**
1. **H1** — bind `Person/:uuid` to the token's patient UUID (one-line, highest
   exploitability).
2. **H3** — parameterize the eye_mag `LIKE` query.
3. **M2** — `attr_js()` the `PHP_SELF`/`SERVER_NAME` output (breaks the XSS
   chain).
4. **H4** — set core `cookie_secure=true` and uncomment the HTTPS redirect.
5. **H2** — add a session MFA-completion flag enforced in `authCheckSession()`.
6. **H6** — add an ACL check to `fax_view.php`; **M3** — add
   `CsrfUtils::checkCsrfInput()` to the ~13 handlers (start with lab sign-off +
   payment deletion).
7. Work **M1 / M4 / M6** and the Low list as hardening.

**Data-durability & at-rest hardening (for any long-lived instance):**
- **C2** — mount a persistent volume over `sites/` so redeploys don't wipe
  documents + keys.
- **C1** — enable disk/volume encryption on the database host, or document the
  field-encryption limitation as an accepted risk.
- **C3** — enable ATNA remote syslog to move audit logs off-host and make them
  tamper-resistant.

---

## Scope & limitations

This is a source-driven audit, **not a running-instance penetration test** — no
exploits were executed against a live stack, so exploitability assessments are
code-based. Coverage was broad but not exhaustive over a codebase this size;
`custom_modules` and the Zend modules received lighter coverage than core. This
report does **not** constitute a formal HIPAA compliance certification.

--------------------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------------------

# Performance Audit

**Planned AI agent profile (drives the recommendation):** read-only, real-time (clinician waits), model hosted on an **external LLM API**, integration path (REST/FHIR vs in-process PHP vs direct DB) **undecided** — this audit compares them and recommends.

---

## Executive summary

1. **A large, uncached fixed per-request "tax" dominates latency** — paid identically on page loads and API calls, before any useful work. Almost nothing is cached across requests.
2. **Loading a patient chart is many DB round-trips**, and a few hot queries can't use their indexes (notably `forms` on encounter open).
3. **The PHP-FPM execution model — not the database — is the hard constraint for a real-time agent:** a ~60s request ceiling, no async, no streaming through PHP, connection-per-request, and session-write serialization.
4. **Recommendation:** run the agent as an **external streaming sidecar**; PHP does only a fast, bounded, session-read-only handoff; assemble patient context in **one batched read** rather than many small FHIR calls. Add missing indexes before load testing.

Encryption is **not** a factor for the agent: no clinical/demographic PHI is encrypted, so reads aren't decryption-bound and search/indexing is unaffected.

---

## 1. The fixed per-request tax (the dominant cost)

Every request — page *and* API — pays this before doing useful work, and there is **no application-level cache** (no APCu/memcached/PSR-16; Redis, when present, is session storage only).

| Fixed cost, every request | Where | Notes |
|---|---|---|
| Full `globals` table reload (~800 rows) into `OEGlobalsBag` | `interface/globals.php:450` | API calls too — `SiteSetupListener.php:202` `require`s globals.php |
| phpGACL ACL caching **hard-disabled** → dozens of `gacl_*` JOINs to build/filter the menu | `src/Gacl/Gacl.php:68`, `src/Menu/MenuRole.php:69` | Page path; largest single per-page DB cost. Cache_Lite code exists but is never enabled |
| API bearer-auth: **~10 DB round-trips + 1 RSA verify + 3 audit INSERTs + 2× SHA3-512** | `src/RestControllers/Authorization/BearerTokenAuthorizationStrategy.php:141`; `src/Common/Auth/UuidUserAccount.php:65,100` | `UuidUserAccount` probes both `users` and `patient_data` even when the role is known from the token |
| Audit-log write (encrypted double-INSERT) on every request | `EventAuditLogger::logHttpRequest`, `interface/globals.php:849` | Synchronous, on the hot path |
| 2 session-tracker queries (idle-timeout bookkeeping) | `src/Common/Session/SessionTracker.php:47,69` | 1 SELECT + 1 UPDATE per request |
| Twig recompiles every render (cache disabled); `Environment`+loader re-instantiated ~9×/page | `src/Common/Twig/TwigContainer.php:70` | No compiled-template cache dir configured |
| Composer autoloader not optimized; 126 files eager-`require`d | `composer.json` config block | Relies entirely on host OPcache; no `optimize-autoloader`/`classmap-authoritative` |
| Modules system booted every request | `interface/globals.php:748` | Registers event listeners each hit |

**Per-call breakdown, FHIR read `GET /fhir/Patient/{uuid}`:** ~80–90% auth + globals bootstrap, ~5% data fetch (one indexed row), ~5% serialization. 

**The data is the cheap part.**

**Per-call breakdown, FHIR search `GET /fhir/Patient?name=…`:** ~30–40% fixed auth/bootstrap, ~15% data fetch, ~45–55% serialization — the latter grows O(N) with result count and is **unbounded when `_count` is omitted** (`SearchQueryConfig.php:52`, `QueryPagination.php:20` `DEFAULT_LIMIT=0`, `MAX_LIMIT=200`). No streaming; the whole bundle is materialized in memory and `json_encode`d twice.

---

## 2. Data model — how a chart loads, and the indexing gaps

### How a patient chart is assembled (data flow)
1. **Demographics:** `getPatientData($pid)` (`library/patient.inc.php:68`) = 1 query; plus per-type insurance (`:361`), employer (`:449`), history (`:338`). Name helpers each re-query `patient_data`.
2. **Summary page:** a fixed base set + ~2 queries per enabled card (allergies, problems, meds, prescriptions, labs, vitals, appointments) — **≈ 30–50 queries per render** [inference], gated by globals/ACLs/modules.
3. **Opening an encounter:** `getFormByEncounter` (1 query) then a loop over every form including its `report.php` (`interface/patient_file/encounter/forms.php:873`, `src/Common/Forms/FormReportRenderer.php:34`) — **≈ 1 + M×(2–3) queries** for M forms. The core N+1 of chart rendering.

### Prioritized data-model findings
- **P0 — `forms` full-scans on every encounter open.** `SELECT … FROM forms WHERE encounter=? AND deleted=0` (`src/Services/FormService.php:33`) cannot use `KEY(pid,encounter)` because `encounter` isn't the leading column → full scan of one of the hottest tables (`sql/database.sql:2476`). **Fix:** add `KEY(encounter, deleted)`.
- **P0 — LBF forms are O(N fields) point queries.** `lbf_data` is EAV with only `PRIMARY KEY(form_id, field_id)` (`sql/database.sql:10236`); the render/edit path calls `lbf_current_value` once per field (`library/options.inc.php:4789`) → 16–127 queries per form. A single-query assembly exists elsewhere (`interface/main/ippf_export.php:358`) but isn't used on the render path.
- **P0 — writes are doubled and land in an unbounded, weakly-indexed table.** Every INSERT/UPDATE/DELETE writes a second `log` row via `auditSQLEvent` (`library/ADODB_mysqli_log.php` → `src/Common/Logging/EventAuditLogger.php:405,524`). `log` has only `KEY(patient_id)` (`sql/database.sql:7758`) and grows forever. **SELECTs are NOT audited by default** (`:440`) → reads are cheap; writes are not.
- **P1 — missing per-patient/lookup indexes:**
  - `audit_master` has only `PRIMARY KEY(id)` — no `pid` index (`sql/database.sql:149`).
  - `openemr_postcalendar_events.pc_pid` not indexed (`sql/database.sql:8261`) →
    "appointments for patient X" scans. Fix: `KEY(pc_pid, pc_eventDate)`.
  - `lists` has separate `KEY(pid)` and `KEY(type)` but no composite
    `(pid, type)` — the ubiquitous `WHERE pid=? AND type='medication'` uses only one.
  - `billing` has only `KEY(pid)` — none on `encounter`/`code`/`date`.
  - `documents` not indexed on `encounter_id` (`sql/database.sql:1391`).
- **P1 — service-layer N+1s:** `InsuranceService` does 2N+1 (`:205-215`, per-row `getUuidById`); `ProcedureService` similar (`:475+`). `BaseService::search` itself is clean (single query + in-memory UUID conversion). `BaseService` constructor runs 2 uncached `SHOW COLUMNS` per instantiation (`:65-73`).

### Encryption impact — none for the agent
No clinical/demographic PHI is encrypted (`patient_data`, `lists`, `form_*`, `history_data`, `pnotes` are plaintext). Encryption is limited to secrets fetched by exact key/id (`keys.value`, `login_mfa_registrations.var1`, `oauth_clients.client_secret`, encrypted-type `globals`). **No indexing/search penalty; bulk reads aren't decryption-bound.** (Document *file bytes* are filesystem-encrypted when `drive_encryption` is on, but row metadata stays plaintext/indexable.)

---

## 3. Execution-model constraints (what actually bites a real-time agent)

Hard limits of the synchronous PHP-FPM/Apache stack:

- **~60s request ceiling**, three converging limits: `max_execution_time=60` (`docker/flex/configs/php8.4/php.ini:409`), `default_socket_timeout=60` (`:879`), and Apache's default `Timeout` (no `ProxyTimeout` in `docker/flex/openemr.conf`). A slow/multi-step LLM call in-request blows it.
- **No async, no streaming through PHP.** The `pcntl_*` family is disabled    php.ini:323`) — parallel LLM calls run serially against the 60s budget — and `output_buffering=4096` + HTTP/1.1-only (`openemr.conf:46`) means **LLM tokens   cannot be streamed to the browser through the PHP render path**.
- **Blocking pins a DB connection.** Connection-per-request with pooling **off** by default (`src/BC/DatabaseConnectionFactory.php:137,150`); a request blocked on an LLM holds its connection the whole time → enough of them exhaust `max_connections` and starve the app.
- **Session lock:** `read_and_close` means concurrent **reads parallelize** (`src/Common/Session/Storage/ReadAndCloseNativeSessionStorage.php:90`), but a single `$_SESSION` **write re-locks** (`SessionUtil::withWritableSession`, `:179`). The agent endpoint must be **session-read-only**. Avoid the `$sessionAllowWrite=true` entry points (main frameset, login, form-save).
- **No real job queue.** No `symfony/messenger`/AMQP/Redis-broker in `composer.json`. `background_services` (`sql/database.sql:189`, `src/Services/Background/BackgroundServiceRunner.php`) is a **minute-granularity, cron/poll-triggered** subprocess runner — subprocess isolation + `set_time_limit(0)` are good for **batch offload**, but it is not interactive and not push.
- **Events are synchronous** (`src/Core/Kernel.php:226`, standard`symfony/event-dispatcher`) — an LLM call in an on-save/on-render listener blocks the user's action. A listener should only *enqueue*, never *call*.
- **Crypto (mostly moot here):** per-field AES-256-CBC + HMAC-SHA384 on decrypt (`src/Common/Crypto/CryptoGen.php:221`); reuse **one** `CryptoGen` instance across a batch to keep the key cache warm. Irrelevant for clinical reads since that data is plaintext.
- **No API rate limiting** anywhere in the REST/FHIR stack — an agent can issue unlimited calls, each paying the full fixed tax.

---

## 4. Recommendation — where the agent should sit

The external LLM call (100s ms–seconds) is the latency floor, and the PHP request path is a hostile place to spend it (60s ceiling, no async/streaming, connection pinning). Therefore:

**Run the agent as an external sidecar service** (Node/Python/PHP-CLI worker) that owns LLM connections, streaming, retries, and concurrency. The browser streams from the sidecar via **SSE**, bypassing PHP output buffering and the 60s ceiling. PHP's only role is a fast, **session-read-only, bounded auth handoff** (mint a short-lived scoped token / hand over a patient-context id).

### Context-assembly read path — options (worst → best for read-only/real-time)

| Option | Latency | Trade-off |
|---|---|---|
| **Existing REST/FHIR** | Worst | Clean + ACL/audit enforced, but pays the ~800-row globals reload + ~10-query auth + 3 audit INSERTs **per call**, no default pagination, no streaming. OK at low call volume; painful for multi-resource turns. |
| **In-process PHP "gather-context" endpoint** | Medium | One session-read-only endpoint that batches the whole patient context in a few JOINs → JSON to the sidecar. Avoids per-resource auth multiplication; pays the bootstrap tax once. **Assemble context only — never make the LLM call here.** |
| **Direct read (read replica)** | Best | Read-only + PHI-unencrypted + SELECTs-unaudited make this cheap and fast. Bypasses ACL scoping and read-audit — fine on the synthetic-data demo; re-add access checks for real PHI. |

**Recommended hybrid:** external sidecar for orchestration + streaming; a **single batched context fetch** (in-process endpoint on the demo, or direct read-replica for minimum latency) instead of many small FHIR reads; PHP does a bounded, session-read-only handoff. Fetch a patient's context in one shot, not resource-by-resource.

---

## 5. Quick wins that help every request (app and agent)

Independent of the agent design, these attack the fixed tax:
1. **Enable phpGACL ACL caching** (`Gacl.php:68`) and/or cache the built menu — kills the per-page `gacl_*` JOIN storm.
2. **Set a Twig cache dir** and stop re-instantiating `Environment`/loader per call (`TwigContainer.php:70`).
3. **`optimize-autoloader: true`** (and consider `classmap-authoritative`) for production images.
4. **Cache the `globals` (and `list_options`) load** behind an app cache instead of a full-table read every request.
5. **Move the per-request audit INSERT off the hot path** (async/queue).
6. **Add the missing indexes:** `forms(encounter,deleted)`, `openemr_postcalendar_events(pc_pid,pc_eventDate)`, `audit_master(pid)`, `lists(pid,type)`, `billing(encounter)`, `documents(encounter_id)`.
7. **Plan retention/partitioning** for the unbounded tables: `log`, `audit_master`/`audit_details`, `documents`, `session_tracker`.

---

## Scope & limitations

Source-driven audit; **no live profiling or load testing** was performed, so query counts per page and cost shares are structural estimates (marked as inference where relevant), not measured timings. Validate the hot paths with real timing (slow query log, `EXPLAIN`, an APM trace, or the Selenium/Panther harness) before committing to an architecture. Query-count-per-page figures scale with each deployment's menu/form/ACL/module configuration.

--------------------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------------------

# Architecture Audit

## Summary

§1 Organization — Three code generations behind one event bus: legacy procedural (library/+interface/), Laminas/Zend MVC modules (zend_modules/), and modern PSR-4 (src/). Front doors: globals.php (pages), apis/dispatch.php (REST/FHIR), bin/console (CLI), portal/ (portal). The Symfony EventDispatcher in src/Core/Kernel.php is the cross-generation spine.

§2 Where data lives — Schema by domain (~282 tables, one flat dump, relations by convention not FKs). Access stack: sqlconf.php → DatabaseConnectionFactory → ADODB (live) / QueryUtils (same connection); Doctrine is scaffolded but dormant. Physical multi-tenancy (one DB + filesystem tree per site). Documents/keys/certs live under sites/<site>/documents/. Config layers sqlconf → config.php → globals table → OEGlobalsBag. Identity via uuid_registry.

§3 How layers interact — Traced both request pipelines (legacy globals.php page flow; Symfony event-driven API flow), the uniform Controller → BaseService → QueryUtils → ADODB chain, the event-wiring model, and the deliberately-inconsistent DI (src/BC/ is the bridge).

§4 Extension points — Ranked catalog: custom module (the container), the event catalog (~90 events with concrete UI/data/config seams), REST/FHIR via RestApiCreateEvent, BaseService, menu/LBF forms, OAuth2/SMART, ACL, globals — each with a how-to and an in-tree skeleton to copy (oe-module-dashboard-context, oe-module-claimrev-connect, oe-module-comlink-telehealth).

§5 Where your AI agent plugs in (the payoff — reconciles architecture with the perf audit): a custom module for the in-EHR surface (patient-context card / navbar widget via events) + config in module globals + a read-only batched context endpoint, but with LLM orchestration/streaming in an external sidecar — because a synchronous LLM call in the PHP request path hits the 60s ceiling and can't stream. Session-read-only throughout.

---

## 0. Executive overview

OpenEMR is a **per-site, single-database PHP application** with three code generations coexisting behind one event bus:

- **Legacy procedural** (`library/`, `interface/**`, `controllers/`, `portal/`, `ccr/`) — globals-based scripts that `require interface/globals.php`.
- **Laminas/Zend MVC modules** (`interface/modules/zend_modules/`) — a middle generation; avoid for new work.
- **Modern PSR-4** (`src/` under `OpenEMR\`, `templates/` Twig, `apis/`, `bin/`) — `declare(strict_types=1)`, constructor DI, `BaseService`.

The **Symfony `EventDispatcher`** created in `src/Core/Kernel.php` is the spine that lets all three communicate. Config flows `sqlconf.php → config.php → globals table → OEGlobalsBag`. The live data path is **ADODB** (`$GLOBALS['adodb']['db']`), fronted by legacy `sql.inc.php` functions and modern `QueryUtils` (both hit the same connection); **Doctrine DBAL/ORM/Migrations are scaffolded but dormant**. New capabilities plug in as **custom modules** (`interface/modules/custom_modules/oe-module-*`) that subscribe to events.

---

## 1. System organization & layering

### Directory taxonomy
| Dir | Purpose | Generation |
|-----|---------|------------|
| `/src` | Modern PSR-4 (`OpenEMR\`): Services, RestControllers, Core kernel, FHIR, Events, Crypto, Common | Modern |
| `/library` | Legacy procedural `*.inc.php` + `classes/*.class.php` (classmap). Bootstrap helpers, `sql.inc.php` | Legacy |
| `/interface` | Web UI pages (`patient_file/`, `billing/`, `main/`, `login/`), the `globals.php` bootstrap, and `modules/` | Legacy (+ hosts modules) |
| `/templates` | Twig templates (~199) — modern presentation | Modern |
| `/apis` | REST/FHIR: `dispatch.php` front controller + `routes/*.inc.php` route tables | Modern |
| `/portal` | Patient portal — separate front door | Legacy-style |
| `/ccr` | CCR/CCD clinical-document XML export | Legacy |
| `/controllers` | Root legacy `C_*.class.php` controllers via `/controller.php` | Legacy |
| `/sql` | `database.sql` + versioned `*_upgrade.sql` migrations | — |
| `/bin` | `bin/console` (Symfony Console), `command-runner` | Modern |
| `/sites` | Per-site config + document/key stores (multi-tenant roots) | — |
| `/gacl` | Bundled phpGACL access-control backend | Legacy vendored |
| `/public`, `/vendor` | Static assets (webpack output); Composer deps | — |

### Entry points (front doors)
- **`/index.php`** — thin redirector: resolve `$site_id`, include `sqlconf.php`, redirect to login/setup.
- **`interface/globals.php`** (863 lines) — the **legacy bootstrap** required by nearly every page: autoload → `OEGlobalsBag` → `new Kernel` (`:376`) → open DB (`:384`) → load `globals` table (`:450`) → `auth.inc.php` (`:726`) → `new ModulesApplication` (`:748`) → HTTP audit log (`:849`).
- **`apis/dispatch.php`** — REST/FHIR front controller → `ApiApplication->run()` (Symfony HttpKernel).
- **`bin/console`** — Symfony Console CLI (`--skip-globals` for DB-less commands).
- **`interface/main/tabs/main.php`** — authenticated frameset (Twig + Knockout).
- **`portal/index.php`** — patient portal front door.

### Framework stack (where each lives)
- **Laminas MVC** — only under `interface/modules/zend_modules/module/*` (config `zend_modules/config/application.config.php`).
- **Symfony components** — `EventDispatcher` (system-wide bus), `HttpKernel`/`HttpFoundation` (REST via `OEHttpKernel`), `Console`, `DependencyInjection` (Kernel container), plus Cache/Routing/Yaml/Process.
- **Twig 3** — modern presentation (`templates/`, rendered via `TwigContainer`). **Smarty 4** — legacy corners only.
- **Front-end** — server-rendered PHP + Knockout.js in the frameset; Angular 1.8 / jQuery / Bootstrap 4.6 elsewhere; Webpack 5 → `public/`.
- **DB** — Doctrine DBAL 4 + Migrations + ORM present but dormant; **ADODB is the live surface**.

### Bootstrap composition
- **`src/Core/Kernel.php`** — Symfony `ContainerBuilder` DI container + `EventDispatcher` (`RegisterListenersPass`). Path accessors; `getContainer()`/`getEventDispatcher()`.
- **`src/Core/ModulesApplication.php`** — builds the Laminas `ServiceManager` and **injects the Symfony `EventDispatcher` into it** (the cross-framework bridge), then boots Laminas + custom modules.
- **`src/Core/OEHttpKernel.php`** — Symfony HttpKernel used by `ApiApplication`.
- **`bootstrap.php`** — clean-room PSR-11 bootstrap (no DB/session/globals); the intended future path, used only by an experimental CLI today.

### "Which generation is this code?" quick guide
- **Legacy:** `require globals.php`, `$GLOBALS`/`$_SESSION`, `sqlStatement()`, `text()`/`xl()`, no namespace, `*.class.php`.
- **Laminas module:** lives in `zend_modules/`, has `Module.php` + `config/module.config.php` + `src/Controller/*`.
- **Modern:** `src/` under `OpenEMR\`, `declare(strict_types=1)`, constructor DI, `extends BaseService`, `QueryUtils`/`OEGlobalsBag`, Twig.
- **Custom module (modern-leaning):** `interface/modules/custom_modules/oe-module-*`, self-registers `OpenEMR\Modules\…` namespace at runtime, subscribes to Symfony events.

---

## 2. Where data lives

### Database schema by domain (`sql/database.sql`, ~282 tables, one flat dump)
- **Clinical:** `patient_data` (keyed by `pid`), `history_data`, `insurance_data`; `form_encounter` (visit, `pid`+`encounter`), `forms` (registry linking every form instance to an encounter), the `form_*` data tables; `lists` (allergies/problems/meds, discriminated by `lists.type`), `prescriptions`, `immunizations`; `procedure_order/report/result`.
- **Scheduling:** `openemr_postcalendar_events` (keyed by `pc_eid`), `patient_tracker`.
- **Billing:** `billing`, `claims`, `ar_activity`, `ar_session`, `fee_schedule`, `codes`, `code_types`.
- **Documents:** `documents` (metadata + storage pointer), `categories`, `document_templates`.
- **Admin/config:** `globals`, `users`, `users_secure`, `facility`, `list_options`, `layout_options`, `modules`, `background_services`, phpGACL `gacl_*`.
- **Audit:** `log` (main trail) + `log_comment_encrypt`, `api_log`, `extended_log`. Note `audit_master`/`audit_details` is the **portal change-approval queue**, not a general audit log.
- **Auth/OAuth:** `oauth_clients`, `api_token`, `api_refresh_token`, `onetime_auth`, `login_mfa_registrations`.
- **Identity:** `uuid_registry`, `uuid_mapping`, `keys`, `migrations`, `version`.

Relations are **by convention** (shared `pid`/`encounter`/`form_id` columns + indexes), not enforced FK constraints.

### DB access stack (bottom → top)
1. **`sites/<site>/sqlconf.php`** — DB credentials only (pre-DB bootstrap).
2. **`src/BC/DatabaseConnectionOptions.php`** — `final readonly` value object; `::forSite()` loads sqlconf + auto-detects MySQL TLS certs under `sites/<site>/documents/certificates/`.
3. **`src/BC/DatabaseConnectionFactory.php`** (`@deprecated`) — `createAdodb()` (live), `createDbal()`, `createMysqli()`.
4. **ADODB surface** — `library/sql.inc.php:59` stashes `$GLOBALS['adodb']['db']` (an `ADODB_mysqli_log` object that also fires the SQL audit log). Legacy `sqlStatement()`/`sqlQuery()`/`sqlInsert()` live here (thin wrappers).
5. **`QueryUtils`** (`src/Common/Database/QueryUtils.php`) — preferred modern static API, but **rides the same ADODB connection** (`getADODB()` returns `OEGlobalsBag->get('adodb')['db']`, `:486`). Legacy `sqlStatement()` now delegates *forward* into QueryUtils.
6. **Doctrine DBAL/ORM/Migrations + `ConnectionManager`/`ConnectionType`** — scaffolded, essentially no runtime consumers; schema still ships via `sql/database.sql` + `*_upgrade.sql`.

### Multi-site / tenancy
One **MySQL database per site** (full physical isolation, not row-level). `OE_SITE_DIR = sites/<site_id>`; site resolved from session/`?site=`/host (`interface/globals.php:272-326`), regex-validated, with a cross-site session-fixation guard. Documents, keys, and TLS certs are all per-site under `OE_SITE_DIR/documents/`.

### Non-DB data stores
- **Documents:** `documents` row holds metadata + pointer; bytes on filesystem `sites/<site>/documents/…` or optional **CouchDB** (`document_storage_method` global; `library/classes/Document.class.php`, `CouchDB.class.php`).
- **Encryption keys (hybrid):** DB key set in the `keys` table encrypts *drive* data; drive key set in files at `sites/<site>/documents/logs_and_misc/methods/` encrypts *DB* data — a deliberate cross-dependency (`src/Common/Crypto/CryptoGen.php`).
- **Sessions:** native **file** handler by default; optional **Redis** via `SESSION_STORAGE_MODE=predis-sentinel`.
- **EDI/ERA:** `sites/<site>/documents/edi/` and `/era/`. **TLS certs:** `…/documents/certificates/`.

### Config layering (what lives where)
`sqlconf.php` (DB creds) → `sites/<site>/config.php` (per-site PHP constants) → **`globals` table** (bulk runtime admin settings, `gl_name`/`gl_index`/`gl_value`, + per-user `user_settings` overrides) → **`OEGlobalsBag`** (in-memory typed aggregator; new code reads `getString/getInt/getBoolean`). Defaults/metadata for globals live in `library/globals.inc.php`.

### Identity: UUID system
`uuid_registry` (binary(16) PK) stamps a UUID onto each externally-addressable row's own `uuid` column; `UuidRegistry` (`src/Common/Uuid/`) is the allocator with a hardcoded table→PK map; `uuid_mapping` covers FHIR sub-resources without their own table. UUIDs are the external identifier for REST/FHIR.

### Data-model conventions
Patient (`patient_data.pid`) ⇒ Encounter (`form_encounter`, `pid`+`encounter`) ⇒ Form: a `forms` row (`formdir`, `form_id`) joins to the specific `form_*` table row. **LBF (Layout-Based Forms):** `layout_options` (field defs) + `list_options` (dropdowns) as metadata; `lbf_data`/`lbt_data` as generic EAV value stores.

---

## 3. How the layers interact

### Web page request lifecycle
```
Browser → interface/<area>/<page>.php
  require globals.php  →  autoload, OEGlobalsBag, session, resolve site,
                          new Kernel (:376), open DB (:384), load globals (:450),
                          auth.inc.php (:726), new ModulesApplication (:748),
                          HTTP audit log (:849)
  → Header::setupHeader()   (assets; fires ScriptFilterEvent / StyleFilterEvent)
  → AclMain::aclCheckCore('patients','demo')   (ACL gate)
  → TwigContainer->getTwig()->render(...)       (HTML out; fires TwigEnvironmentEvent)
```
Auth (`library/auth.inc.php`) dispatches on `?auth=` (login/logout/else→`authCheckSession()`); ACL via `AclMain::aclCheckCore()` runs a phpGACL query and renders `unauthorized-partial.html.twig` on deny.

### API / FHIR request lifecycle (Symfony HttpKernel, event-driven)
```
apis/dispatch.php → ApiApplication::run() registers subscribers, then OEHttpKernel::handle():
  kernel.request  SiteSetupListener (prio 100)   → resolve site, start session, require globals.php (:202)
  kernel.request  AuthorizationListener (prio 50) → strategies: LocalApi / SkipAuth / BearerToken (PEP #1)
  kernel.request  RoutesExtensionListener (prio 40)→ RouteFinder loads apis/routes/_rest_routes_*.inc.php
                    → HttpRestRouteHandler::dispatch() → checkSecurity() fires RestApiSecurityCheckEvent (PEP #2, scope check)
                    → sets _controller to a closure invoking the route callback
  (controller)    route closure news-up a RestController → Service → QueryUtils
  kernel.view     ViewRendererListener → wrap result as JsonResponse/text
  kernel.terminate SessionCleanup / Telemetry / ApiResponseLogger
```

### Service → DB chain
```
Controller/page → Service (extends BaseService) → QueryUtils → ADODB (ADODB_mysqli_log) → mysqli
```
`BaseService` (`src/Services/BaseService.php:65`) caches table fields, pulls the logger from `ServiceContainer`, and grabs the dispatcher from `OEGlobalsBag->getKernel()->getEventDispatcher()`. FHIR services (`src/Services/FHIR/FhirServiceBase.php`) wrap a standard service search and `parseOpenEMRRecord()` into FHIR objects.

### Event system & module wiring
The Kernel's `EventDispatcher` (`src/Core/Kernel.php:57,226`) is injected into the Laminas ServiceManager by `ModulesApplication`, which then `include`s each active custom module's `openemr.bootstrap.php` (registers namespace, `new Bootstrap($dispatcher)->subscribeToEvents()`), and dispatches `ModuleLoadEvents::MODULES_LOADED`. Two registration styles: `addListener(EventClass::CONST, $cb, $prio)` and `addSubscriber($subscriberImplementingEventSubscriberInterface)`. ~90 event classes under `src/Events/`.

### DI reality
Deliberately inconsistent: the API side is event-driven/injected; services still reach through static locators (`ServiceContainer`, `OEGlobalsBag::getInstance()`) and `new`. `OEGlobalsBag` (singleton) + `$GLOBALS` are the shared-state substrate; `src/BC/` is the explicit backward-compat bridge.

---

## 4. Integration & extension points (how to add capabilities)

**Central mechanism:** a custom module is a class that receives the shared
`EventDispatcher` and calls `addListener(...)`. Everything below is a variation.

1. **Custom module** (highest leverage — the container for everything else). `interface/modules/custom_modules/oe-module-*` with `openemr.bootstrap.php` (namespace registration + `new Bootstrap($dispatcher)->subscribeToEvents()`), `moduleConfig.php` (metadata: menu/globals/tables/acl), `src/Bootstrap.php` (the single wiring point), `ModuleManagerListener` (install/enable/disable/upgrade via `AbstractModuleActionListener`), `sql/install.sql`. Registered in the `modules` table; loaded by `ModulesApplication::bootstrapCustomModules()`. **Skeletons to copy:** `oe-module-dashboard-context` (clean UI/menu/globals), `oe-module-claimrev-connect` (REST+FHIR+scopes+globals+Twig), `oe-module-comlink-telehealth` (full-featured).

2. **Event system** (the actual extension surface). Notable seams:
   - UI injection: `Patient/Summary/Card/SectionEvent` (`addCard()`), `UserInterface/PageHeadingRenderEvent` (navbar widget), `PatientDemographics/RenderEvent`, `Core/ScriptFilterEvent` / `StyleFilterEvent` (global JS/CSS), `Core/TwigEnvironmentEvent` (template overrides/filters), `Main/Tabs/RenderEvent` (app-wide scripts).
   - Data hooks: `Patient/PatientCreatedEvent` (+Before/Updated), `Services/ServiceSaveEvent`, `Appointments/*`, `Encounter/*`.
   - Config/menu: `Globals/GlobalsInitializedEvent`, `Menu/MenuEvent::MENU_UPDATE`.

3. **REST/FHIR endpoints from a module** — listen to `RestApiExtend/RestApiCreateEvent` and call `$event->addToRouteMap("GET /api/foo/:id", fn)` (or `addToFHIRRouteMap`/`addToPortalRouteMap`). Companion events: `RestApiScopeEvent` (register OAuth scopes), `RestApiResourceServiceEvent` (register a FHIR service class for the capability statement), `RestApiSecurityCheckEvent` (custom auth). In-tree examples: `oe-module-dorn`, `oe-module-claimrev-connect`.

4. **Service layer** — extend `BaseService` (`const TABLE_NAME`, `parent::__construct(self::TABLE_NAME)`) for UUID/CRUD/validation plumbing; FHIR services under `src/Services/FHIR/`.

5. **UI / menu / forms** — `MenuEvent::MENU_UPDATE` (append items under a parent `menu_id`), the LBF/layout engine (`layout_options` via Admin→Layouts) for data-driven forms, coded forms under `interface/forms/`.

6. **OAuth2 / SMART-on-FHIR** (external-app path) — `src/Common/Auth/OpenIDConnect/`, dynamic client registration (`AuthorizationController::clientRegistration`, RFC 7591), `oauth_clients` table, SMART launch, `.well-known/smart-configuration`. Register a client, request scopes (`patient/*.read`, `user/*.read`, `system/*.read`), obtain a token, call `/apis/default/fhir/...`.

7. **ACL / permissions** — declare `acl_category`/`acl_section` in `moduleConfig.php`, ship ACL setup in install SQL (`modules.acl_version` tracks it), guard code with `AclMain::aclCheckCore(section, value)`.

8. **Global settings** — listen to `GlobalsInitializedEvent`, use `GlobalsService` (`createSection` + `appendToSection(..., new GlobalSetting(...))`), or declare in `moduleConfig.php` `globals[]`. Read via `OEGlobalsBag`.

---

## 5. Where the planned AI agent plugs in

Profile: **read-only, real-time, external LLM, integration path undecided** (see `PERF_AUDIT.md`). Reconciling the extension points with the performance constraints:

**Recommended: a custom module `oe-module-ai-agent` for the in-EHR surface + config, with LLM orchestration in an external streaming sidecar.**

- **UI (module, event-driven):** inject a patient-context assistant via
  `Patient/Summary/Card/SectionEvent::addCard()` or a navbar widget via
  `PageHeadingRenderEvent::appendTitleNavContent()`, load JS via
  `ScriptFilterEvent`/`Main\Tabs\RenderEvent`. No core edits.
- **Config (module globals):** API key/endpoint via `GlobalsInitializedEvent` — keeps secrets server-side, never in the browser.
- **Read path (module or direct):** a read-only module REST route (`RestApiCreateEvent`) that fans out to `BaseService` reads under `AclMain`, assembling a patient's context in **one batched call** (not many small FHIR reads — each FHIR call is ~80–90% fixed auth/globals overhead per `PERF_AUDIT.md`).
- **Do NOT run the LLM call in the PHP request path or an event listener** — the ~60s `max_execution_time`/socket/Apache ceiling, no async, no output streaming, and connection-per-request pinning make that unsafe. The module hands off to an **external sidecar** that owns the LLM connection, streaming (SSE to the browser), retries, and fan-out.
- **Keep the agent endpoint session-read-only** (a single `$_SESSION` write re-locks and serializes the user's concurrent requests).
- **Alternative (fully external app):** skip the UI and use OAuth2/SMART with read scopes over FHIR — standard scoping/auditing, out-of-process, but pays the per-call FHIR overhead.

---

## 6. Cross-cutting architectural notes

- **One event bus, three generations.** The Symfony `EventDispatcher` is the only clean seam that spans legacy, Laminas, and modern code — prefer it over patching.
- **`src/BC/` is the bridge** (DatabaseConnectionFactory, ServiceContainer, FallbackRouter) — explicitly backward-compat, `@deprecated` in places.
- **Doctrine is the stated future but dormant;** ADODB is today's runtime path, and it also fires the per-query audit log.
- **Config and shared state** run through `OEGlobalsBag` + `$GLOBALS`; the `globals` table is reloaded per request (see `PERF_AUDIT.md`).
- **Multi-tenancy is physical** (DB + filesystem per site), not row-level.

## 7. Key file index
`interface/globals.php`, `apis/dispatch.php`, `bin/console`, `bootstrap.php` ·
`src/Core/{Kernel,OEHttpKernel,ModulesApplication,ModulesClassLoader,Header,OEGlobalsBag}.php` ·
`src/RestControllers/ApiApplication.php` + `Subscriber/{SiteSetup,Authorization,RoutesExtension,ViewRenderer}Listener.php` ·
`src/Common/Http/HttpRestRouteHandler.php`, `apis/routes/_rest_routes*.inc.php` ·
`src/Services/BaseService.php`, `src/Services/FHIR/FhirServiceBase.php` ·
`src/Common/Database/QueryUtils.php`, `library/sql.inc.php`, `library/ADODB_mysqli_log.php`, `src/BC/DatabaseConnection*.php` ·
`src/Common/Acl/AclMain.php`, `src/Common/Twig/TwigContainer.php`, `src/Common/Uuid/UuidRegistry.php`, `src/Common/Crypto/CryptoGen.php` ·
`src/Events/**`, `src/Menu/**`, `src/Services/Globals/GlobalsService.php` ·
`interface/modules/custom_modules/oe-module-dashboard-context/**` (module skeleton) ·
`sql/database.sql`, `sites/<site>/{sqlconf.php,config.php}` ·

## Scope & limitations
Source-driven architecture map, not a runtime trace. Table/event counts and "which layer is live" reflect the code as read; deployment config (site count, enabled modules, storage backend) varies per install.


--------------------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------------------


# Data Quality Audit

## Executive summary — the root causes

Four structural root causes generate nearly every finding below:

1. **`NOT NULL DEFAULT ''` everywhere** collapses "missing" and "blank" into the
   same empty string, so incompleteness is *undetectable in aggregate*.
2. **Coded concepts stored as unconstrained `varchar`** (no FK, no CHECK) — the
   same attribute (sex, race, diagnosis) is spelled and compared differently
   across subsystems.
3. **Zero foreign keys and no natural-key uniqueness** — integrity is purely
   by-convention; duplicate patients and orphan rows are structurally possible
   and only reactively cleaned.
4. **Inconsistent soft-delete/activity conventions and missing last-modified
   columns** — stale rows leak differently per table, and demographic staleness
   is unknowable at the row level.

For the planned **read-only AI agent** (see `PERF_AUDIT.md`,
`ARCHITECTURE_AUDIT.md`), the practical impact is: it cannot trust that a field's
emptiness means "not collected," cannot assume a canonical spelling for coded
values, may see the same patient as multiple `pid`s, and may read long-resolved
problems still flagged active. Every one of these needs handling in the
context-assembly layer.

---

## 1. Completeness / missing fields

**Root pattern:** most demographic and many clinical columns are
`varchar(255) NOT NULL DEFAULT ''` (`patient_data` `sql/database.sql:8337-8443`,
`procedure_order:10377`, `form_encounter:2041`), so an unknown value and a
deliberately-blank value are identical (`''`). Nullable tables (`insurance_data`
`:3309`, `lists` `:7674`, `prescriptions` `:8701`) at least preserve the missing
signal but do not force population.

**Only 4 patient fields are required anywhere** — `fname`, `lname`, `sex`, `DOB`
(`src/Validators/PatientValidator.php:56-59`, layout `uor=2`). Everything USCDI
needs for a usable chart is optional and unconstrained:

| Field | Column | Schema | Required? |
|---|---|---|---|
| fname / lname / sex | `:8340/8341/8360` | `NOT NULL DEFAULT ''` | yes (validator + layout) |
| DOB | `:8343` | `date DEFAULT NULL` | yes |
| SSN, race, ethnicity, language, address, phone, email, pubpid, PCP | `:8350-8379` | `NOT NULL DEFAULT ''` (or `int NULL`) | **no** |

Key findings:
- **Required-field enforcement is largely client-side JS only.**
  `generate_layout_validation()` emits browser validation
  (`library/options.inc.php:4325`, skips `uor<2` at `:4368`); the legacy save
  path `demographics_save.php:186` only tests `isset`. Any import, API bypass, or
  scripted write can persist a patient with blank `fname`/`sex`.
- **Two enforcement layers disagree.** `PatientValidator` (REST/FHIR only)
  requires `sex` length 4–30 (`:58`) — rejecting short list codes — and is
  entirely separate from the legacy UI path.
- **Clinical completeness gaps** (all optional):
  - Problems/allergies without codes — `lists.diagnosis DEFAULT NULL` (`:7687`);
    `ConditionValidator.php:34` makes `diagnosis` optional.
  - Meds without RxNorm — `prescriptions.rxnorm_drugcode DEFAULT NULL`,
    `drug_id NOT NULL DEFAULT '0'` (`:8709`); `drug_id=0` = "no coded drug".
  - Immunizations essentially unvalidated — `ImmunizationValidator` is an empty
    stub (`:21-24`); `cvx_code`/`administered_date` nullable.
  - Encounters with no forms; orders with no results (`procedure_report`/
    `procedure_result` nullable chain; `order_status`/`result_status`
    `NOT NULL DEFAULT ''` so "no status" == blank).

→ Profiling: **Appendix A, §1** (completeness rates, orphan charts, uncoded
clinical rows).

---

## 2. Consistency / inconsistent formatting

**Priority 1 — coded concepts as free text.** Closed-set attributes are
`varchar(255)` holding a `list_options.option_id` with **no FK, no CHECK**
(`patient_data.sex/race/ethnicity/status/language`, plus `gender_identity`/
`sexual_orientation` as TEXT). Seed defines `sex` option_ids `Female`/`Male`/
`UNK`, but code disagrees on representation:
- `library/FeeSheet.class.php:150` — `strtoupper(substr(sex,0,1))=='M'` (first
  letter) — the canonical `'M'` vs `'Male'` divergence.
- `src/Billing/Hcfa1500.php:344` — exact `== 'M'` (would fail against `Male`).
- `src/RestControllers/PatientRestController.php:54,123` — documents `'Male'`.

The same attribute is compared three different ways; a consumer cannot assume one
canonical spelling.

**Priority 2 — no input normalization** for names/phones/addresses. The
demographics save path (`PatientService.php:168`) does no phone or name
normalization — `(555) 123-4567`, `555.123.4567`, `5551234567`, `+15551234567`
all persist verbatim. A capable `src/Services/PhoneNumberService.php`
(E.164/HL7) exists but operates on a **separate `phone_numbers` table**, not the
`patient_data.phone_*` columns — inconsistency by architecture.

**Priority 3 — boolean drift.** At least four encodings coexist:
`tinyint(1)` (×138), `tinyint(4)`/bare `tinyint` used as bool (×118),
`char(1)` (×17), and ENUMs `enum('Y','N')` (`:1654`), `enum('Yes','No')`
(`:12563`), `enum('0','1')`. Defaults for the *same* `active`/`activity` concept
vary between `0`, `1`, and `NULL` across tables. `globals` stores booleans as
text (`YES/NO/1/0/Y/N`).

**Priority 4 — dates.** Mostly canonical (storage `DateToYYYYMMDD`
`library/formatting.inc.php:165`; display `oeFormatShortDate` `:26`), but some
dates are **free text**: `erx_rx_log.date varchar(25)` (`:1795`), immunization
registry `*_effdate` as TEXT (`:8432`), `procedure_result.*_tz varchar(5)`
offsets. Storage-vs-display formatters can round-trip through localized strings;
parallel JS formatters (`formatting_DateToYYYYMMDD_js.js.php`) can diverge.
*(Zero-dates absent in this pruned schema — live-DB risk only.)*

**Priority 5 — delimited composite codes.** `lists.diagnosis varchar(255)`
(`:7687`) packs `codetype:code` pairs joined by `;` (written
`interface/patient_file/summary/add_edit_issue.php:576`, parsed
`stats_full.php:333`). `billing.code_type`/`code`/`modifier`/`justify` are
string-referenced to `code_types.ct_key`, not FK-enforced — leading-zero/dotted-
ICD/casing variance unconstrained.

**Priority 6 — charset.** No `CHARSET`/`COLLATE` declared anywhere in this pruned
schema → charset inherited from server defaults at install, so two installs of
the *same schema* can differ (utf8mb4 vs latin1/utf8mb3) → mojibake/collation
mismatch. *(Live-DB risk; profile per Appendix A §2.)*

→ Profiling: **Appendix A, §2** (distinct value spellings, list_options orphans,
phone shapes, free-text dates, charset audit, composite-code integrity).

---

## 3. Duplicates / uniqueness / referential integrity

**Zero foreign keys.** No `CONSTRAINT`/`REFERENCES` clauses across ~255 tables;
relationships are documented only in comments. Integrity is purely by-convention.

**No natural-key uniqueness on patients** (`patient_data` `:8467`): the only
unique keys are synthetic `pid` and `uuid`. **No uniqueness on `pubpid` (MRN),
`ss` (SSN), or (lname,fname,DOB)** — name/DOB indexes exist but are non-unique.
Nothing at the DB layer prevents inserting the same person twice.

**Orphan-row risk** (all nullable, unconstrained): `forms.pid/encounter/form_id`
(`:2463`, with `forms.deleted` soft-delete so orphans persist), `lists.pid`
(`:7690`), `documents.foreign_id` (`:1404`), `ar_activity.session_id`/`pid`.

**`users.username` not uniquely constrained** — `UNIQUE KEY USERNAME_ID
(id,username)` (`:9889`) is satisfied by any row (id is already PK); username
uniqueness depends entirely on app code.

**`pid` via `MAX(pid)+1`** (`PatientService.php:151`, `patient.inc.php:1030`) —
not atomic, does **not** use the `sequences`/`GenID` mechanism (which *is* used
for `forms.form_id`). Concurrent registrations can collide (hard insert failure);
deleting a high-pid patient lets `MAX+1` **reuse** a retired pid.

**Dedup is reactive, not preventive.** A scoring tool
(`manage_dup_patients.php`, weights in `library/dupscore.inc.php:18` — **SSN not
in the match score**) writes `patient_data.dupscore`; manual merge via
`merge_patients.php`. **No de-dup gate on insert**, and `ListService` has no
uniqueness — the same problem/allergy/med can be added repeatedly. Portal
self-registration funnels through the `audit_master` approval queue (human
review, not a constraint).

**UUIDs are well-guarded** — `uuid_registry PRIMARY KEY(uuid)` + per-table
`UNIQUE KEY uuid` + collision-retry in `UuidRegistry::getUnusedUuidBatch()`
(`:380`). Residual risk: rows with `uuid IS NULL`/unregistered until a backfill
runs.

→ Profiling: **Appendix A, §3** (dup patients by name+DOB / SSN / pubpid, orphan
forms/lists/documents/AR, dup list entries, UUID gaps).

---

## 4. Staleness / reliability + shipped reference data

**Priority 1 — three incompatible soft-delete conventions.** Learn one, mis-read
another:
- `deleted tinyint (1=deleted)` — `forms:2470`, `documents:1422`, `pnotes:8681`.
- `deleted datetime (NULL=active, else voided)` — **`ar_activity:10207`** (the
  trap: copy the `deleted=0` idiom here and you invert active/voided financials).
- `activity tinyint (1=active), DEFAULT NULL` — `lists:7688`.

`lists.activity` **defaults to NULL**, so a row inserted without an explicit
value is invisible to `activity=1` (the majority, ~372 call sites) and visible
to `activity!=0` (~4 sites); ~53 raw `lists` queries carry **no** activity filter
at all — the population where soft-deleted problems/allergies/meds leak into
reports and API output.

**Priority 2 — no last-modified column where it matters.** `patient_data` has
**no update timestamp** (only `date` = creation) — a record edited yesterday and
one untouched 10 years is indistinguishable at the row level. (Siblings that *do*
track it: `form_encounter.last_update`, `lists.modifydate`,
`immunizations.update_date` — `ON UPDATE CURRENT_TIMESTAMP`.)
`prescriptions.date_modified` is set manually in PHP, not DB-enforced, so writes
bypassing `Prescription::persist()` leave it stale.

**Priority 3 — contradictory "active" state.** Nothing reconciles `activity`/
`active` against `enddate`/`end_date`: a `lists` problem with `activity=1` and a
past `enddate`, or a `prescriptions` row `active=1` with a past `end_date`,
persists uncleaned. **"Long-resolved problem still marked active" is a real,
unguarded state** — exactly the kind of thing an AI agent would surface as
current.

**Priority 4 — unbounded tables, no shipped purge.** `log`, `session_tracker`,
`onsite_portal_activity`, `payment_processing_audit`, `audit_master` grow without
any retention routine; `documents` retains `deleted=1` and past-`date_expires`
rows.

**Reference-data quality (what actually ships):**
- **CVX immunization codes** — `sql/cvx_codes.sql`, **231 rows** (code_type 100):
  a **static snapshot** (max code ~511), with **retired vaccines still flagged
  `active=1`** (e.g. CVX 15/18 labeled "-retired" but active). No recent/COVID-era
  entries.
- **`list_options`** — ~2,235 rows (rich, complete for core UI dropdowns).
- **`code_types`** — 16 types defined; **15 rows in `codes`** total + the CVX set.
- **What does NOT ship (fresh install = empty vocab):** every external code set is
  empty — `icd10_dx_order_code`, `icd9_dx_code`, `snomed`, `rxnorm`, `valueset`
  all **0 rows**; CPT-4/HCPCS are copyrighted and ship empty. So a fresh install
  has **usable CVX + list_options + 15 drug-form codes only** — ICD-10/9, CPT-4,
  HCPCS, SNOMED, RxNorm, CQM valuesets are empty until an admin runs the external
  loader. An agent reasoning over a fresh DB finds problem/procedure/med `code`
  columns blank or free-text, with **no error raised**.

→ Profiling: **Appendix A, §4** (soft-delete ratios per convention, NULL-activity
leak set, contradictory active state, stale demographics via last encounter,
aging documents, log growth, vocab-emptiness check, retired-but-active CVX).

---

## 5. Top risks for an AI agent reading a chart (cross-cutting)

1. **Empty ≠ missing** (`NOT NULL DEFAULT ''`) — the agent cannot distinguish
   "not collected" from "unknown/blank" on most fields.
2. **Same patient, multiple `pid`s** — no natural-key uniqueness; dedup is
   reactive. Resolve identity before trusting a single chart.
3. **No canonical spelling for coded values** — `sex` = `M`/`Male`/`male`/`UNK`
   depending on the writer; normalize against `list_options` on read.
4. **Uncoded clinical data** — problems/meds may carry free-text or blank codes;
   on a fresh install the entire ICD/CPT/SNOMED/RxNorm vocab is empty.
5. **Stale "active" flags** — long-resolved problems and ended prescriptions can
   read as current; cross-check `enddate`/`end_date` and status, don't trust
   `activity`/`active` alone.
6. **Soft-delete convention varies per table** — must apply the right filter
   (`deleted=0` vs `deleted IS NULL` vs `activity=1`) per table or leak stale rows.
7. **Demographic staleness is unknowable** on `patient_data` (no modified-time) —
   proxy via last encounter.

---

## 6. Remediation priorities (if hardening the data model)

Schema/enforcement fixes, highest leverage first:
1. **Server-side required-field enforcement** mirroring the client layout
   (`options.inc.php:4368`) — today the legacy save path trusts the browser.
2. **Promote USCDI fields to required** (race, ethnicity, language, address,
   phone) and/or enforce in `PatientValidator`; fill `ImmunizationValidator`.
3. **Convert genuinely-optional `NOT NULL DEFAULT ''` columns to nullable** so
   "missing" becomes queryable — the empty-string sentinel is the root blocker.
4. **Add uniqueness / matching on patient identity** (at least a unique `pubpid`
   and a real dedup gate on insert); include SSN in the match score.
5. **Normalize coded values on write** (validate against `list_options`) and
   **normalize phones/names** via the existing `PhoneNumberService`.
6. **Standardize the soft-delete convention** (or centralize a "not-deleted"
   query helper per table) and **add `ON UPDATE CURRENT_TIMESTAMP` to
   `patient_data`**.
7. **Add a reconciliation job** to flip `activity`/`active` when `enddate`/
   `end_date` passes; **retention/purge** for `log`/audit tables.
8. **Refresh CVX** and load external vocabularies before clinical use.

For the AI agent specifically, most of this can be **handled at read-time in the
context-assembly layer** (identity resolution, coded-value normalization,
active-state reconciliation, per-table soft-delete filters) rather than requiring
schema migrations — appropriate for a read-only assistant on demo data.

---

## Appendix A — Profiling query pack (run against a live DB)

> Run against your demo/production database to convert the structural risks above
> into real numbers. Grouped by dimension. (MySQL.)

### §1 Completeness
```sql
-- Demographic completeness (empty '' or NULL) on high-value patient fields
SELECT COUNT(*) AS total_patients,
  ROUND(100*SUM(fname='' OR fname IS NULL)/COUNT(*),1)            AS pct_missing_fname,
  ROUND(100*SUM(sex='' OR sex IS NULL)/COUNT(*),1)                AS pct_missing_sex,
  ROUND(100*SUM(DOB IS NULL OR DOB='0000-00-00')/COUNT(*),1)      AS pct_missing_dob,
  ROUND(100*SUM(race='' OR race IS NULL)/COUNT(*),1)              AS pct_missing_race,
  ROUND(100*SUM(ethnicity='' OR ethnicity IS NULL)/COUNT(*),1)    AS pct_missing_ethnicity,
  ROUND(100*SUM(`language`='' OR `language` IS NULL)/COUNT(*),1)  AS pct_missing_language,
  ROUND(100*SUM(ss='' OR ss IS NULL)/COUNT(*),1)                  AS pct_missing_ssn,
  ROUND(100*SUM(street='' AND city='' AND postal_code='')/COUNT(*),1) AS pct_missing_address,
  ROUND(100*SUM(phone_home='' AND phone_cell='' AND phone_biz='')/COUNT(*),1) AS pct_missing_phone,
  ROUND(100*SUM(providerID IS NULL OR providerID=0)/COUNT(*),1)   AS pct_missing_pcp
FROM patient_data;

-- Patients with no encounter; encounters with no forms
SELECT COUNT(*) AS patients_without_encounter
FROM patient_data p LEFT JOIN form_encounter fe ON fe.pid=p.pid WHERE fe.id IS NULL;
SELECT COUNT(*) AS encounters_without_forms
FROM form_encounter fe LEFT JOIN forms f
  ON f.pid=fe.pid AND f.encounter=fe.encounter AND f.deleted=0 WHERE f.id IS NULL;

-- Uncoded problems/allergies/meds; meds w/o RxNorm; immunizations w/o CVX/date; orders w/o results
SELECT `type`, COUNT(*) rows_total,
  ROUND(100*SUM(diagnosis='' OR diagnosis IS NULL)/COUNT(*),1) pct_missing_code
FROM lists WHERE `type` IN ('medical_problem','allergy','medication') GROUP BY `type`;
SELECT COUNT(*) rx_total, SUM(rxnorm_drugcode='' OR rxnorm_drugcode IS NULL) rx_no_rxnorm,
       SUM(drug_id=0) rx_no_drug_id FROM prescriptions WHERE active=1;
SELECT COUNT(*) imm_total, SUM(cvx_code IS NULL OR cvx_code='') missing_cvx,
       SUM(administered_date IS NULL) missing_date FROM immunizations WHERE added_erroneously=0;
SELECT COUNT(*) AS orders_without_results
FROM procedure_order po
LEFT JOIN procedure_report prpt ON prpt.procedure_order_id=po.procedure_order_id
LEFT JOIN procedure_result  prr  ON prr.procedure_report_id=prpt.procedure_report_id
WHERE po.activity=1 AND prr.procedure_result_id IS NULL;
```

### §2 Consistency / formatting
```sql
-- Distinct spellings of a coded field (repeat for race/ethnicity/status/language)
SELECT sex AS raw_value, COUNT(*) n FROM patient_data GROUP BY sex ORDER BY n DESC;
-- Values that are NOT valid list_options ids (free-text / orphan codes)
SELECT pd.sex, COUNT(*) n FROM patient_data pd
LEFT JOIN list_options lo ON lo.list_id='sex' AND lo.option_id=pd.sex
WHERE pd.sex<>'' AND lo.option_id IS NULL GROUP BY pd.sex ORDER BY n DESC;

-- Zero/empty-date sweep generator (produces per-column probes to run)
SELECT CONCAT("SELECT '",TABLE_NAME,'.',COLUMN_NAME,"' col, COUNT(*) zeros FROM `",
  TABLE_NAME,"` WHERE `",COLUMN_NAME,"` IN ('0000-00-00','0000-00-00 00:00:00') HAVING zeros>0 UNION ALL")
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA=DATABASE() AND DATA_TYPE IN ('date','datetime','timestamp');

-- Phone format variety
SELECT CASE
  WHEN phone_cell REGEXP '^[0-9]{10}$'          THEN '10-digit-bare'
  WHEN phone_cell REGEXP '^\\+?1?[0-9]{10,11}$' THEN 'e164-ish'
  WHEN phone_cell REGEXP '[(). -]'              THEN 'punctuated'
  WHEN phone_cell=''                            THEN 'empty' ELSE 'other' END AS shape,
  COUNT(*) n FROM patient_data GROUP BY shape ORDER BY n DESC;

-- Charset/collation audit (mojibake risk): anything not utf8mb4
SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES
WHERE TABLE_SCHEMA=DATABASE() AND TABLE_COLLATION NOT LIKE 'utf8mb4%' ORDER BY 2,1;

-- Diagnosis composite-string integrity in lists
SELECT SUM(diagnosis LIKE '%;%') multi_code,
       SUM(diagnosis NOT LIKE '%:%' AND diagnosis<>'') missing_codetype_prefix
FROM lists WHERE diagnosis IS NOT NULL;
```

### §3 Duplicates / integrity
```sql
-- Duplicate patients by name+DOB, by SSN, by pubpid
SELECT LOWER(TRIM(lname)) lname, LOWER(TRIM(fname)) fname, DOB, COUNT(*) n,
       GROUP_CONCAT(pid ORDER BY pid) pids
FROM patient_data WHERE DOB IS NOT NULL AND TRIM(lname)<>'' AND TRIM(fname)<>''
GROUP BY 1,2,3 HAVING n>1 ORDER BY n DESC;
SELECT ss, COUNT(*) n, GROUP_CONCAT(pid) pids FROM patient_data
WHERE TRIM(ss)<>'' AND ss REGEXP '[0-9]' GROUP BY ss HAVING n>1 ORDER BY n DESC;
SELECT pubpid, COUNT(*) n, GROUP_CONCAT(pid) pids FROM patient_data
WHERE TRIM(pubpid)<>'' GROUP BY pubpid HAVING n>1;

-- Orphans: forms / lists / documents / ar_activity
SELECT f.id,f.pid,f.encounter,f.form_id FROM forms f
LEFT JOIN patient_data p ON p.pid=f.pid
LEFT JOIN form_encounter e ON e.encounter=f.encounter AND e.pid=f.pid
WHERE f.deleted=0 AND (p.pid IS NULL OR (f.encounter<>0 AND e.encounter IS NULL));
SELECT l.id,l.pid,l.type FROM lists l LEFT JOIN patient_data p ON p.pid=l.pid WHERE p.pid IS NULL;
SELECT d.id,d.foreign_id FROM documents d LEFT JOIN patient_data p ON p.pid=d.foreign_id
WHERE d.foreign_id IS NULL OR d.foreign_id=0 OR p.pid IS NULL;
SELECT a.pid,a.session_id FROM ar_activity a LEFT JOIN ar_session s ON s.session_id=a.session_id
WHERE a.session_id<>0 AND s.session_id IS NULL;

-- Duplicate active list entries within a patient
SELECT pid,type,LOWER(TRIM(title)) title,diagnosis,COUNT(*) n FROM lists
WHERE activity=1 GROUP BY 1,2,3,4 HAVING n>1 ORDER BY n DESC;

-- UUID gaps (unregistered/NULL) — collisions are blocked by PKs
SELECT 'patient_data' tbl, COUNT(*) missing FROM patient_data pd
LEFT JOIN uuid_registry r ON r.uuid=pd.uuid
WHERE pd.uuid IS NULL OR pd.uuid=0x00000000000000000000000000000000 OR r.uuid IS NULL;
```

### §4 Staleness / reference data
```sql
-- Soft-delete ratios (each convention stated explicitly)
SELECT 'forms' tbl, SUM(deleted=1)/COUNT(*) ratio, COUNT(*) tot FROM forms
UNION ALL SELECT 'documents', SUM(deleted=1)/COUNT(*), COUNT(*) FROM documents
UNION ALL SELECT 'ar_activity(datetime!)', SUM(deleted IS NOT NULL)/COUNT(*), COUNT(*) FROM ar_activity
UNION ALL SELECT 'lists(activity)', SUM(activity=0 OR activity IS NULL)/COUNT(*), COUNT(*) FROM lists;

-- lists rows with NULL activity (the leak set)
SELECT type, COUNT(*) FROM lists WHERE activity IS NULL GROUP BY type ORDER BY 2 DESC;

-- Contradictory active-but-resolved state
SELECT 'problem/med active w/ past enddate' issue, COUNT(*) FROM lists
WHERE activity=1 AND enddate IS NOT NULL AND enddate<CURDATE()
UNION ALL SELECT 'rx active w/ past end_date', COUNT(*) FROM prescriptions
WHERE active=1 AND end_date IS NOT NULL AND end_date<CURDATE();

-- Stale demographics via last encounter (no per-row modified time exists)
SELECT pd.pid, MAX(fe.date) last_encounter FROM patient_data pd
LEFT JOIN form_encounter fe ON fe.pid=pd.pid GROUP BY pd.pid
HAVING last_encounter IS NULL OR last_encounter<DATE_SUB(NOW(),INTERVAL 3 YEAR)
ORDER BY last_encounter;

-- Aging documents; unbounded log growth
SELECT SUM(deleted=1) soft_deleted,
       SUM(date_expires IS NOT NULL AND date_expires<NOW()) expired_present,
       COUNT(*) total FROM documents;
SELECT DATE_FORMAT(date,'%Y') yr, COUNT(*) rows_in_year FROM log GROUP BY yr ORDER BY yr;

-- Vocabulary emptiness (is this a fresh install with no coded data?)
SELECT 'ICD10' t, COUNT(*) c FROM icd10_dx_order_code
UNION ALL SELECT 'SNOMED', COUNT(*) FROM snomed
UNION ALL SELECT 'RXNORM', COUNT(*) FROM rxnorm
UNION ALL SELECT 'CVX shipped', COUNT(*) FROM codes WHERE code_type=100;

-- Retired-but-active CVX vaccines
SELECT code, code_text, active FROM codes
WHERE code_type=100 AND code_text LIKE '%RETIRED%' AND active=1;
```

---

## Scope & limitations
Structural/enforcement audit of a **pruned schema with no patient data**, plus
inspection of shipped reference data — **not** a profile of real records. All
"how much" questions require running Appendix A against a live DB. Zero-dates and
charset divergence are absent from this tree but are live-DB risks (profiled
anyway). Query-count figures (e.g. the 372-vs-4 `lists.activity` split) are grep
counts over `library/`+`src/`+`interface/` and approximate the risk surface, not
a per-query correctness verdict.

---

## Appendix B — Live DB verification (development-easy stack)

Run 2026-07-06 against the running dev database (`openemr`, MariaDB 11.8,
`development-easy-mysql-1`). This confirms/refines the structural findings with
real numbers.

**The database is a fresh install with NO clinical data** — so the patient-data
profiling (§1–4 completeness/consistency/duplicates/staleness) has nothing to
measure yet. Row counts: `patient_data` 0, `form_encounter` 0, `lists` 0,
`prescriptions` 0, `documents` 0; only `log` has 4,089 rows (app HTTP audit
logging from setup). **To profile clinical-data quality, synthetic demo patients
must be loaded first.**

**Reference-data quality — verified live (this IS present):**
- `codes` total = **246 rows, ALL CVX** (`code_type=100`). No CPT/HCPCS/ICD codes
  in `codes` at all.
- **2 retired-but-active CVX codes** confirmed (`code_text LIKE '%RETIRED%' AND active=1`).
- External vocab tables: `icd10_dx_order_code` = **0**, `icd9_dx_code` = **0**,
  `valueset` = **0**; **`snomed` and `rxnorm` tables do not exist** (created only
  when the external loader runs). So a fresh install has **no ICD/CPT/HCPCS/
  SNOMED/RxNorm/valueset vocabulary** — stronger than the schema audit implied.
- `list_options` = **5,605 rows** (well-populated); `code_types` = **18** defined.

**Schema as actually built — verified live:**
- **0 foreign-key constraints** in the whole `openemr` schema
  (`information_schema.REFERENTIAL_CONSTRAINTS`) — integrity is by-convention, confirmed.
- `patient_data` unique keys: **`pid` and `uuid` only**; `DOB` and
  `(lname,fname)` are non-unique — the duplicate-patient risk, confirmed at the
  index level.
- **Charset is uniform** here: all 283 tables `utf8mb4_general_ci`. The
  pruned-schema charset-divergence risk did **not** materialize on this install
  (server default applied uniformly) — though `general_ci` (not `unicode_ci`) is
  the collation.
- `sql_mode` = `STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION`
  — **lacks `NO_ZERO_DATE`/`NO_ZERO_IN_DATE`**, so `'0000-00-00'` values are still
  permitted on this server (the zero-date risk is live, just not yet exercised by
  any data).

**Bottom line:** every *structural/reference-data* finding that can be checked
without patient rows is confirmed on the live DB. The *clinical* data-quality
numbers await synthetic demo data being loaded.

---

## Appendix C — Live profiling of OpenEMR's OFFICIAL demo data

The container's version-matched **`sql/example_patient_data.sql`** was loaded
into the dev DB and Appendix A run against it (2026-07-06). This is OpenEMR's
**own shipped sample — 14 patients, demographics only** (the file touches
`patient_data` only; no encounters/problems/meds), so the clinical-completeness
and staleness dimensions (§1-clinical, §4) have no rows and are N/A here. The
demographic findings below are **real, independent results** from the official
data, not a synthetic construction.

**§1 Completeness (14 official demo patients) — real gaps:**
- **`sex` missing on 4/14 (29%)** — and `sex` is a *"required"* field. OpenEMR's
  **own sample data violates its own requirement**, confirming empirically that
  required-field enforcement is not applied on the write/import path.
- **`race` 14/14 missing (100%)**, **`ethnicity` 14/14 missing (100%)** — the
  official demo carries no race/ethnicity at all (both USCDI elements).
- `language` 2/14 missing; DOB, SSN, address, `pubpid` all populated (0% missing).
- **`uuid` NULL on 14/14 (100%)** — `example_patient_data.sql` inserts no UUIDs
  and registers none, so every official demo patient is **unregistered** in
  `uuid_registry` until a backfill runs (the exact structural risk from §3,
  confirmed on real shipped data).

**§2 Consistency — actually clean in the official data:** `sex` values are valid
`Male`/`Female` (plus the blanks above), `language` uses valid lowercase
`list_options` ids (`english`/`spanish`), and phones are uniformly punctuated
(13 punctuated, 1 empty). **No formatting chaos** in the official sample — the
consistency *risks* documented in §2 are real (nothing prevents them) but the
shipped demo does not exhibit them. (An earlier synthetic run *did* exhibit them,
but that only reflected injected data, so it is not reported as a finding.)

**§3 Duplicates / integrity — real hit:** a **duplicate SSN — `555-11-1111`
shared by 2 of the 14 patients** — present in OpenEMR's own demo and **undetected
by the DB** (no uniqueness constraint on `patient_data.ss`). No name+DOB or
`pubpid` duplicates in this sample.

**What this establishes (on OpenEMR's real shipped data):**
1. A "required" field (`sex`) is blank on 29% of the official demo — enforcement
   gap, proven.
2. Race/ethnicity are 100% absent — the USCDI-completeness risk is real, not
   hypothetical.
3. 100% of demo patients carry unregistered NULL UUIDs.
4. A duplicate SSN ships in the demo with no constraint to catch it.

To profile *your* real quality, point the validated Appendix A pack at your
production/patient data and re-run. (For clinical/staleness numbers you need a
dataset with encounters/problems/meds — the official demo is demographics-only;
the OpenEMR `demo-data-generator` tool or a Synthea import produces a fuller
clinical cohort.)

### Appendix C.1 — OpenEMR `demo-data-generator` cohort (100 patients)

Ran OpenEMR's own `demo-data-generator` (needed a shim: it emits a 2017-era
column `interpretter` dropped in 8.2, and `''` for numeric columns under STRICT
mode — staged through a text table). **Also demographics-only** (no clinical
events), so it does not unlock the clinical/staleness dimensions. Findings on the
100 generated patients:
- **race 100% / ethnicity 100% / language 100% / `pubpid` 100% / `uuid` 100%
  missing** — confirms the optional-field + unregistered-UUID gaps at larger N.
- `sex`/`DOB`/`ss` fully populated; formatting clean *within* the set (`sex`
  Male/Female, SSN bare-9-digit, phone `(nnn)nnn-nnnn`); no duplicates.
- **Cross-dataset inconsistency:** the generator's SSN format (bare 9-digit)
  differs from the official demo's (dashed `nnn-nn-nnnn`) — combining sources
  would inject exactly the kind of format drift §2 warns about.

**Net:** two independent OpenEMR-supplied demographic datasets both show 100%
race/ethnicity/language absence and 100% unregistered UUIDs. Clinical-data quality
(uncoded problems/meds, stale-active, orphan encounters) still needs a Synthea/
clinical import to measure.


--------------------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------------------


# Compliance & Regulatory Audit

## Executive summary

OpenEMR provides audit and access-control **mechanisms**, but leaves the **policy and enforcement primitives** that HIPAA compliance actually turns on either missing or cosmetic. Four structural themes recur:

1. **The audit trail is not legally defensible** — read/view logging is inferred (session-derived patient id), there's no source IP for web actions, and tamper-evidence is an unkeyed hash co-located with the data. You cannot reliably answer "who accessed which patient's chart."
2. **There is no retention or disposal engine at all** — nothing purges the ever-growing audit tables, "deleting" a document never removes the file from disk, and no setting expresses any retention period.
3. **Breach notification would be crippled** — because affected individuals can't be reliably enumerated and PHI isn't encrypted at rest (no safe harbor), OpenEMR can't scope a breach or rebut the breach presumption.
4. **The LLM agent adds a Business-Associate relationship and a new disclosure surface** — workable *only* with a provider BAA, minimum-necessary payloads, a distinct audited principal, and a record of exactly what PHI was sent.

For the **demo (synthetic data)** none of this binds. For any **real-PHI** deployment or agent, these are gating.

---

## §1 Audit logging & audit controls

**Requirements:** §164.312(b) audit controls · §164.308(a)(1)(ii)(D) activity review · §164.528 accounting of disclosures.

**Logging path:** every DB query → `ADODB_mysqli_log::Execute()`
(`library/ADODB_mysqli_log.php:50`) → `EventAuditLogger::auditSQLEvent()`
(`src/Common/Logging/EventAuditLogger.php:405`); explicit events via `newEvent()`;
API via `ApiResponseLoggerListener`; all land in `LogTablesSink::record()`
(`src/Common/Logging/Audit/LogTablesSink.php:38`) → `log` + `log_comment_encrypt`
(+ `api_log`), optional ATNA syslog if `enable_atna_audit` (default off).

| Requirement | Status | Evidence |
|---|---|---|
| §164.312(b) record activity | **Partial** | `log` table fed by ADODB hook + explicit events over ~40 mapped tables (`EventAuditLogger.php:107`) |
| §164.308(a)(1)(ii)(D) review tooling | **Implemented** | `interface/logview/logview.php`, `interface/reports/audit_log_tamper_report.php` |
| **PHI read/view — who viewed which chart** | **Gap (weak)** | Patient id copied from **session `pid`**, not the row read (`EventAuditLogger.php:508`); SELECTs from tables not in `LOG_TABLES` are **dropped** (`:501`) |
| Source IP (interactive web) | **Gap** | `log` has **no IP column**; IP only on `api_log.ip_address` + free-text auth-failure comments |
| Event/user/timestamp/success | Partial | user/date/event present; API `success` hardcoded `1` (`ApiResponseLoggerListener.php:91`) |
| §164.528 accounting of disclosures | **Partial** | `extended_log` via `recordDisclosure()` (`:567`) is **manual-entry**, editable & hard-deletable, no auto-capture of CCDA/API exports, **no checksum field** |
| Log integrity / tamper-evidence | **Gap** | Unkeyed `hash('sha3-512',…)` (`LogTablesSink.php:63`), no HMAC secret, no chaining, in-DB with the data — detects naive edits only |
| Log confidentiality | **Gap** | Audit comments = raw SQL + bind values, `'encrypt'=>'No'` (`LogTablesSink.php:89`), base64 only → the audit log is itself an **unencrypted PHI store** |
| Configurability | **Risk** | Auditing fully disableable (`enable_auditlog` + per-category `audit_events_*`, default on, `library/globals.inc.php:2778`); per-category toggles are **not themselves audited** |

Note: `api_log_option` defaults to **2** (full request + response bodies logged), which is good for API auditability but stores PHI in `api_log`.

**Top gaps:** no source IP for web actions; cosmetic tamper-evidence; read-logging can't identify the record actually accessed; manual/mutable disclosure accounting.

---

## §2 Data retention & disposal

**Requirements:** §164.316(b)(2) retain documentation ≥6 yrs · §164.310(d)(2) media re-use/disposal · state medical-record retention (6–10 yrs+, longer for minors).

**Bottom line: OpenEMR ships no retention engine and no disposal engine.** The term "retention" appears nowhere as a setting; there is **no configurable retention period** for anything, and the only automatic deletions are two hardcoded session routines.

| Requirement | Status | Evidence |
|---|---|---|
| Configurable retention period (any data) | **Gap** | No global anywhere in `library/globals.inc.php`; cannot express "retain N years" or a disposal date |
| Audit-log retention lifecycle | **Gap** | `log`, `extended_log`, `api_log`, `audit_master`/`audit_details`, `ip_tracking`, `payment_processing_audit` — **no purge/prune/archival** routine; no `cron/`; none of the 5 seeded background services purges (`sql/database.sql:209`) |
| **Document media disposal (§164.310(d)(2)(i))** | **Gap (serious)** | `delete_document()` only `UPDATE documents SET deleted=1` (`interface/patient_file/deleter.php:185`); **the on-disk file / CouchDB blob is never unlinked** — the PHI byte-stream survives "deletion" forever |
| Document expiry → purge | **Partial** | `documents.date_expires` gates *access* (`Document.class.php:329`) but never deletes; note `has_expired()` logic is **inverted** (`>= time()` true for future dates) |
| Soft-delete → disposal | **Gap** | `forms.deleted`, `documents.deleted`, `pnotes.deleted`, `lists.activity`, `ar_activity.deleted` retained forever; nothing hard-deletes |
| Transient/session disposal | **Implemented (hardcoded)** | `session_tracker` purged after 7 days (`SessionTracker.php:32`); session GC 4 hrs (`SessionUtil.php:96`) — neither configurable, neither touches clinical PHI |
| Backup retention/rotation | **Partial** | `interface/main/backup.php` = on-demand tarball to admin's browser; no schedule, rotation, at-rest encryption, or offsite lifecycle |
| De-identification for research | **Gap** | No anonymization/Safe-Harbor utility; research export = raw PHI |

**Top gaps:** documents are never physically disposed (highest severity); audit tables grow unbounded; zero retention configurability so an operator cannot implement the §164.316(b)(2) 6-year rule or state law through the product.

---

## §3 Breach notification readiness

**Requirements:** §164.400–414 (Breach Notification Rule) — detect → investigate
→ assess (§164.402 four-factor) → notify individuals within 60 days (§164.404),
HHS (§164.408), media for 500+ (§164.406); BA→CE chain (§164.410).

| Capability | Rating | Evidence |
|---|---|---|
| Detect — failed login / lockout | **Supported** | `AuthUtils` + `ip_tracking` counters, auto-block, email |
| Detect — breakglass/emergency access | **Supported** | `gbl_force_log_breakglass` (default 1) forces full logging (`BreakglassChecker.php:39`) |
| Detect — PHI-read auditing | **Partial** | lossy: session-pid attribution + table-name heuristic (`EventAuditLogger.php:486`) |
| Detect — anomaly / alerting | **Gap** | nothing watches bulk/off-hours/one-user-many-patients access |
| Investigate — who/which-patient/when | **Gap** | patient id session-derived → "which patients did this account access?" unanswerable |
| Investigate — tamper-evidence | **Gap** | unkeyed hash, no chaining → audit trail repudiable, not legally defensible |
| **Notify — enumerate affected individuals** | **Gap** | cannot reliably list whose PHI a compromised account touched — the core §164.404 blocker; also breaks the 500+ threshold count |
| Notify — 4-factor risk data (§164.402) | **Partial** | "viewed" inferable; "acquired/exported" unknowable; all facts repudiable |
| **Encryption safe-harbor (§164.402)** | **Does NOT apply** | PHI not encrypted at rest (`AUDIT.md` C1) → any confirmed unauthorized DB access is a **reportable breach with no exemption** |

**Net:** OpenEMR can raise some alarms but cannot reliably *scope* a breach or produce a defensible investigation record — the two things the notification clocks depend on.

---

## §4 BAA implications of sending PHI to an LLM provider

This is the agent-specific crux. **Requirements:** §164.502(e) & §164.308(b) (business associates) · §164.410 (BA breach chain) · §164.502(b) (minimum necessary) · §164.514 (de-identification).

**The core rule:** an external LLM provider that *receives PHI* is a **Business
Associate** — you must have a **signed BAA** before transmitting PHI. Sending PHI
to an LLM **without** a BAA is an **impermissible disclosure** and, under §164.402,
a **presumed breach** unless a four-factor low-probability showing is made — which
OpenEMR cannot support here (unencrypted at rest + repudiable audit trail). The
"conduit exception" does **not** apply: an LLM processes content, it doesn't
merely transmit it.

**Provider reality (Anthropic, the named provider; verified 2026-07):**
- Anthropic **offers a BAA for the first-party Claude API** and Claude Enterprise
  (HIPAA opt-in), with **Zero Data Retention (ZDR)** available to eligible API
  customers — a compliant path exists.
- **The Claude Console (web UI) is NOT covered** by the BAA — PHI must go through
  the BAA-covered API surface, not Console.
- ZDR means inputs/outputs aren't stored (except minimal safety-classifier
  results) — this closes the "provider keeps a second copy of PHI" retention gap.
- Other major providers (OpenAI, Google Vertex/Gemini, AWS Bedrock, Azure OpenAI)
  similarly offer BAAs on eligible tiers — verify current terms per provider.

**Obligations beyond just signing the BAA:**
- **Minimum necessary (§164.502(b)):** send only the chart data the task needs, not entire records. Design the context-assembly to scope tightly.
- **De-identification (§164.514) as an alternative:** if PHI is de-identified (Safe Harbor's 18 identifiers, or Expert Determination) *before* leaving OpenEMR, it isn't PHI and no BAA is needed — but reliable de-identification of free-text clinical notes is hard and error-prone; treat as risk-reduction, not a guarantee.
- **Subprocessors / data-flow:** confirm the provider's subprocessors, region, and that submitted data is **not used for training** (contractually).
- **BA breach chain (§164.410):** if the provider (a BA) is breached, it must notify you within 60 days, cascading you into the §164.404/406/408 clocks. You must be able to **scope** that — which requires a record of exactly what was sent (see §5).

---

## §5 AI-agent compliance obligations (consolidated checklist)

The planned agent is **read-only, real-time, chart-querying, external LLM (Anthropic)**. To make it compliant on a real-PHI deployment, all of the following are required (most are *net-new* — OpenEMR lacks the primitives):

1. **Signed BAA with the LLM provider**, PHI only over the **BAA-covered API**
   (not Console), **ZDR enabled**, no-training contractual terms. *(Gate.)*
2. **Minimum-necessary payloads** — scope context to the query; prefer
   de-identification where feasible.
3. **Route agent PHI access through an audited boundary (API/service), NOT a direct DB connection.** Per §1, a direct DB read produces **zero audit trail**; the in-process path mis-attributes the patient. The compliance-best path is the REST/FHIR API (writes `log`+`api_log` with user/patient/IP/body) — which is in direct tension with the perf audit's "direct read is fastest." Resolve toward the audited path for real PHI.
4. **Give the agent a distinct principal** (its own `authUserID`/token) so its access is attributable and separable from human users.
5. **Log every agent PHI access with the *actual* record/patient id, IP/origin, purpose, and result** — not the session-derived pid.
6. **Record every record/data element sent to the LLM** (an automated disclosure log) so a provider-side breach (§164.410) is *scopeable* — OpenEMR has no such mechanism today.
7. **Make the agent's audit events tamper-evident** (HMAC-keyed + hash-chained, or shipped to the ATNA/WORM sink) — the default checksum is cosmetic.
8. **Retention & disposal for agent transcripts** — prompts/responses/context are PHI records subject to §164.316 retention *and* §164.310(d)(2) disposal; OpenEMR has no purge infrastructure, so this must ship with the feature.
9. **Anomaly monitoring** on the agent's bulk/cross-patient access pattern (exactly what current detection misses).
10. **Demo carve-out:** on the synthetic-data demo none of 1–9 binds; enforce a hard gate so the agent path can never touch real PHI without them.

---

## §6 Remediation priorities (platform-level, if pursuing real-PHI)

1. **Tamper-evident audit log** — HMAC (secret outside the DB) + prev-row chaining (`LogTablesSink.php:63`). Without this no breach finding is defensible.
2. **Fix patient attribution** — parse patient id(s) from query binds, not `$_SESSION['pid']` (`EventAuditLogger.php:508`) — enables affected-individual enumeration.
3. **Encrypt PHI at rest** (incl. the audit-comment column) — restores the breach safe harbor and stops the audit log from being its own PHI leak.
4. **Real document disposal** — unlink the file/blob on delete, honoring configurable retention (`deleter.php:185`); fix the inverted `has_expired()`.
5. **Retention engine** — a configurable retention period + a purge background service for audit/log tables and soft-deleted rows.
6. **Automate disclosure accounting** (§164.528) for exports/API/agent, in a non-mutable, checksummed store.
7. **Source IP on interactive audit events**; anomaly alerting on bulk access.

Several of these overlap `AUDIT.md`'s Criticals (C1 at-rest encryption, C3 tamper-evidence) — resolving those advances both security and compliance.

---

## Scope & limitations

Technical compliance mapping of a pruned base against the HIPAA Security/Privacy/ Breach rules; **not legal advice** and not a certification. "No mechanism exists" claims are grep-negatives over `sql/`, `library/`, `src/`, `interface/`. No live PHI was assessed. Provider BAA terms (Anthropic and others) change — verify current terms with the provider and counsel before transmitting PHI. State-law retention periods are jurisdictional and out of scope.
