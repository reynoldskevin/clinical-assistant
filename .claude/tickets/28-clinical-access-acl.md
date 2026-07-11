---
id: 28
title: ACL gate on token mint — bind agent read to OpenEMR clinical-read rights
status: ready-for-merge
depends_on: []
branch: ticket/28-clinical-access-acl
base_branch: main
test_command: "composer phpunit-isolated -- --filter ClinicalAccessPolicy"
full_suite_command: "composer phpunit-isolated"
attempts: 1
---

## Description
The AI agent's read boundary currently authenticates *who* is asking (session +
CSRF, principal captured in the JWT) and scopes *which* chart (one pid per token),
but performs **no authorization check**: `token.php` mints a scoped token for any
authenticated session that has a patient in context, regardless of the user's
role or clinical-read rights. A logged-in user without clinical access (e.g.
front-desk/billing) could obtain the full clinical summary through the agent even
though OpenEMR would deny them the clinical tabs in the UI.

USER.md (implicit, raised in review): *"The system must know who is asking and
enforce appropriate access — not assume all users are trusted."*

The correct posture for a read-only overlay is **delegate to OpenEMR's own ACL**,
never invent a parallel RBAC: the agent must never read more than the logged-in
human already could. Role differentiation (nurse / resident / attending) and any
configured patient-panel scoping are then inherited from OpenEMR's ACL groups
rather than reimplemented here.

## Acceptance criteria
- [ ] A `ClinicalAccessPolicy` unit decides whether a session user may read
      clinical data by delegating to an injected ACL check (OpenEMR's
      `patients`/`med` section/value). It is the single authorization seam.
- [ ] Grants when the injected ACL check returns true; denies when it returns false.
- [ ] Denies an empty/blank username without consulting the ACL (fail closed).
- [ ] Passes exactly `('patients', 'med', <username>)` to the injected check.
- [ ] `token.php` invokes the policy (wired to `AclMain::aclCheckCore`) after the
      authenticated-session + CSRF checks and BEFORE minting; a denied user gets
      403 and no token is minted. (Wiring — reviewer-verified, per the module's
      thin-endpoint pattern; unit coverage is on the policy.)

## Test plan (orchestrator authors these)
- isolated unit: `tests/Tests/Isolated/Modules/AiAgent/Auth/ClinicalAccessPolicyTest.php`
  - grant path (injected check → true)
  - deny path (injected check → false)
  - empty username → deny, ACL not consulted
  - correct arguments forwarded to the injected check (section/value/username)
