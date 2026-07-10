---
name: tdd-ticket-loop
description: >-
  Orchestrate coding sub-agents through a test-driven, ticket-by-ticket build loop.
  Use AFTER plan mode when the user wants to turn an approved build plan into tickets
  and have Claude Code drive sub-agents to implement them via TDD until acceptance
  criteria pass. Trigger phrases: "run the ticket loop", "orchestrate the build",
  "TDD the plan with sub-agents", "loop sub-agents to build this". Coding tasks only.
---

# TDD Ticket Loop — sub-agent build orchestrator

You (the main Claude Code agent) are the **orchestrator**. You decompose an
approved plan into tickets and drive them to completion one at a time, spawning
sub-agents for implementation and review, running the tests yourself, and looping
until each ticket's acceptance criteria pass. This skill is for **coding tasks
only**.

## Locked design decisions (do not deviate without asking the user)

1. **Sequential** — one ticket at a time, in dependency order. Never run tickets in parallel.
2. **Branch off `main` by default; stack only when a dependency forces it.** Create each new ticket's branch off the latest `main` — the human reviews and merges MRs in order against `main`, so an off-`main` branch gives a clean diff. **Exception (stacking):** when a ticket needs code from a prior ticket that has NOT yet merged to `main` (its tests can't even build without it), branch it off that prior ticket's branch instead. As soon as the prior ticket merges, rebase the stacked branch onto `main` so it becomes a clean off-`main` branch. Never auto-merge into `main`. (Stacking implies a merge-order requirement — see #8.)
3. **Orchestrator authors the tests** — YOU write each ticket's tests (unit + end-to-end as appropriate) from its acceptance criteria, and commit them, BEFORE any implementation. Tests are the contract.
4. **Tests are locked** — the implementer sub-agent may NOT create/edit/delete test files. It writes production code to make the tests pass. If it believes a test is genuinely wrong, it must STOP and report that to you; you decide (fix the test yourself or escalate to the user). After every implementer run, verify the test files are unchanged (`git diff` on test paths); if changed, revert them and re-dispatch with a warning (counts toward the cap).
5. **Orchestrator-controlled loop** — do not trust a sub-agent's claim that tests pass. After each implementer attempt, **run the tests yourself** and read the real output.
6. **Reviewer gate** — after tests are green, spawn a separate reviewer sub-agent to verify the diff against the acceptance criteria and that the tests are meaningful (not gamed) and unchanged. Reviewer rejection feeds back into the loop.
7. **Full regression after green** — once the ticket's own tests pass and the reviewer approves, run the FULL test suite on the branch (it includes accumulated stacked work). A regression halts the ticket for repair before it's marked done.
8. **No merge — push AND open the MR for review instead.** When a ticket reaches ready-for-merge, push the branch **and create its merge request in the same push** using GitLab push options (see Step 6 for the exact command). The human reviews + merges in the GitLab GUI. Never merge to the base branch yourself. Push ONLY completed tickets (never WIP/blocked). A push/MR failure is NOT a ticket failure — report it and continue. Never `--force`.
   - **MR title** = the subject line of the ticket's **feature commit** — the `feat(<id>)`/`fix(<id>)` implementation commit that begins the feature work — **NOT** the `test(<id>)` commit. The scope is the ticket NUMBER (e.g. `feat(17): …`), matching the `test(17): …` commit, so the MR title carries the ticket number for tracking.
   - **MR description** = this ticket's `.claude/tickets/<NN-slug>.md`, **FLATTENED to a single line** (YAML frontmatter stripped, all newlines collapsed to spaces). **git forbids newlines in push-option values** (`fatal: push options must not have new line characters`), so the description MUST be one line — markdown structure is lost but the full text is preserved. See Step 6 for the exact `awk`/`tr` flatten.
   - **Do NOT delete the source branch on merge** — always pass `-o merge_request.remove_source_branch=false` so the MR's "Delete source branch" box is unchecked.
   - **MR target = `main`** — always. The human reviews and merges MRs in order against `main`; do NOT target another ticket's branch.
   - **Stacked dependency → merge prerequisite.** When a ticket was stacked off an unmerged prior ticket (per #2), its MR MUST declare that the prior ticket's MR merges FIRST — prepend `Depends on: !<prev-MR> — merge that before this.  ` (with a trailing space, NOT a newline) to the flattened description so the order can't be violated. Until the prior merges, the MR diff will show the prior's commits too; it cleans up automatically once the prior is in `main` (rebase onto `main` then to tidy it).
   - Push options only take effect on a push that updates a ref, so the completion push MUST be the branch's **first** push — do NOT `git push` the branch earlier in the loop. If the branch is already on `origin` (so options can't fire on an up-to-date push) or the remote rejects push options, fall back to relaying the printed "create merge request" URL — do NOT force-push just to attach options.
9. **No breakdown pause** — decompose and start immediately; do not wait for approval of the ticket list.
10. **Iteration cap → escalate** — each ticket has a max-attempts budget (default **6**). On exhaustion, STOP that ticket, write a clear failure report (what failed, last test output, hypotheses), and ask the user how to proceed. Never loop indefinitely.
11. **Commit hygiene — stage explicit paths only.** When committing a ticket, `git add` ONLY that ticket's own files: its production code, its test file(s), and its own `.claude/tickets/<this-ticket>.md`. NEVER `git add .` or a whole directory (e.g. `git add .claude/tickets`). Because Step 1 writes ALL ticket files up front, a directory add would commit *future* tickets' `.md` files (and any unrelated working-tree edits) onto this ticket's branch — exactly the leak to avoid.

## Config (defaults; confirm/override from the user's request)

- `BASE_BRANCH` = the current branch at invocation (usually `main`).
- `MAX_ATTEMPTS` = 6 per ticket (implementer attempts + reviewer-driven redos combined).
- `TICKETS_DIR` = `.claude/tickets/`.
- **Test runner** — auto-detect; do not hardcode. Detect from the repo:
  PHP → `phpunit`/`composer test` (this repo: `openemr-cmd ut|at|et|st` or `composer phpunit-isolated`);
  JS/TS → `npm test` / `jest`; Python → `pytest`; Go → `go test ./...`. Record the exact command(s) per ticket in its ticket file. If ambiguous, ask the user once.

## Preconditions

- Invoked **after plan mode** with an approved plan (from the plan, `BUILD_PLAN.md`, or the user's message). If no plan is available, ask for one — do not invent scope.
- Working tree is clean (commit/stash first). Confirm the base branch.

## Step 1 — Decompose the plan into tickets

Break the plan into the **smallest independently-testable** units. For each,
write a ticket file `TICKETS_DIR/NNN-slug.md`:

```markdown
---
id: 003
title: get_patient_summary boundary endpoint
status: todo            # todo | tests-authored | implementing | reviewing | regression | ready-for-merge | blocked
depends_on: [001, 002]
branch: ticket/003-get-patient-summary
base_branch: main             # main by default; the previous ticket's branch ONLY if this ticket needs its not-yet-merged code (stacked — see decision #2)
test_command: "openemr-cmd ut -- --filter PatientSummary"
full_suite_command: "openemr-cmd cst"
attempts: 0
---

## Description
<what and why, 2-4 lines>

## Acceptance criteria
- [ ] <observable, testable behavior 1>
- [ ] <behavior 2>

## Test plan (orchestrator authors these)
- unit: <files/cases to write>
- e2e: <files/cases to write>
```

Track the tickets in the session Task list too (one task per ticket). Then begin
executing immediately (no approval pause).

## Step 2 — Per-ticket loop (the core algorithm)

For each ticket in dependency order:

```
1. BRANCH (off `main` by default — see decision #2): git checkout main; git pull;
   git checkout -b <ticket.branch>. STACK instead (base = the prior ticket's branch)
   ONLY when this ticket needs a prior ticket's code that has NOT yet merged to `main`
   — without it the tests can't build. If the prior ticket is already merged to `main`,
   branch off `main` (a `git pull` first picks up that merged code). Record the actual
   base in the ticket's `base_branch`.

2. AUTHOR TESTS (you, the orchestrator): write the unit + e2e tests from the
   acceptance criteria. Run them → confirm they FAIL for the right reason (red).
   STAGE ONLY THIS TICKET'S PATHS: `git add <this ticket's test file(s)> .claude/tickets/<THIS-ticket>.md`.
   NEVER `git add .` or a whole directory (e.g. `git add .claude/tickets`) — Step 1
   writes ALL ticket files up front, so a directory add drags *future* tickets'
   ticket-files (and unrelated working-tree edits) onto this branch. Commit:
   "test(<id>): acceptance tests for <title>". Set status: tests-authored.

3. IMPLEMENT LOOP:
   attempts = 0
   repeat:
     attempts++ ; if attempts > MAX_ATTEMPTS → ESCALATE (see below); stop ticket.
     spawn IMPLEMENTER sub-agent (template below) with: ticket, acceptance criteria,
       the exact test_command, the test-lock rule, and the PREVIOUS failure output.
     verify test files unchanged (git diff --name-only on test paths). If changed →
       revert them, note a warning, continue loop.
     run test_command YOURSELF; read output.
     if all green → break.

4. REVIEW: spawn REVIEWER sub-agent (template below) with the diff + acceptance
   criteria. If it REJECTS → feed its findings back into the IMPLEMENT LOOP
   (attempts keep counting). If it APPROVES → continue.

5. REGRESSION: run full_suite_command on the branch. If it fails → treat as a
   rejection: back to IMPLEMENT LOOP with the regression output (attempts count).

6. DONE: stage ONLY this ticket's paths (`git add <this ticket's production file(s)>
   .claude/tickets/<THIS-ticket>.md` — never `.` or a directory), commit the feature
   work with a `feat(<id>):`/`fix(<id>):` message — the scope is the ticket NUMBER
   (e.g. `feat(17): …`), the SAME scope as the `test(<id>):` commit, so it becomes the
   MR title for ticket tracking. Set status: ready-for-merge. Then PUSH
   AND OPEN THE MR in one push, via GitLab push options (never --force; only completed
   tickets; this must be the branch's FIRST push so the options take effect):

     TITLE=$(git log --format=%s "origin/main..HEAD" | grep -vE '^test\(' | tail -1)
     # Flatten the ticket .md into ONE line: drop YAML frontmatter, collapse newlines
     # to spaces (push options must not contain newlines).
     DESC=$(awk 'BEGIN{fm=0} /^---$/{fm++; next} fm>=2{print}' .claude/tickets/<NN-slug>.md | tr '\n' ' ' | tr -s ' ')
     # STACKED ticket only (decision #2): prepend the merge prerequisite (trailing spaces, no newline):
     #   DESC="Depends on: !<prev-MR> — merge that before this.  $DESC"
     git push -u origin <ticket.branch> \
       -o merge_request.create \
       -o merge_request.target="main" \
       -o "merge_request.title=$TITLE" \
       -o "merge_request.description=$DESC" \
       -o merge_request.remove_source_branch=false

   The MR ALWAYS targets `main`, keeps its source branch (`remove_source_branch=false`),
   and its description is the FLATTENED ticket .md (single line — push options forbid
   newlines). TITLE resolves to the ticket's feature commit subject (the earliest
   non-`test(...)` commit — the `feat/fix` that begins the feature), NOT the test commit.
   GitLab creates the MR server-side over SSH (no token/CLI needed) and prints its URL.
   Because push options only fire on the branch's FIRST (ref-updating) push, get these
   right the first time — you cannot re-fire them on an up-to-date branch, and you must
   NOT force-push to attach them. If the push or MR-create fails (branch already on
   origin, remote rejects push options, auth/network/protected branch), report it and
   fall back to relaying the printed
   "create merge request" URL — the ticket is already done and committed locally.
   Do NOT merge. Report the ticket complete (branch, changes, test results, MR URL).
   Move to the next ticket — branch it off `main` (decision #2), stacking off this
   one ONLY if it needs this ticket's code before this ticket's MR has merged.
```

## Sub-agent prompts (templates)

**Implementer** (spawn via the Agent tool, general-purpose):
> You are implementing ONE ticket via TDD. Ticket: `<paste ticket>`. The tests are
> already written and are the FIXED contract at `<test paths>` — you may NOT
> create, edit, or delete any test file. Run `<test_command>`, then write/modify
> PRODUCTION code only until every test passes. Do not stub or hard-code to fake a
> pass. If a test appears genuinely wrong, STOP and explain why instead of editing
> it. Previous attempt's failures: `<output or "none">`. Return: what you changed
> and the final test output.

**Reviewer** (spawn via the Agent tool; use a code-review agent type if available):
> Adversarially review this diff against the ticket's acceptance criteria. Ticket:
> `<paste>`. Diff: `<git diff base...branch>`. Verify: (a) every acceptance
> criterion is genuinely met; (b) the tests are meaningful and were NOT weakened or
> edited; (c) no hard-coding/stubbing that fakes passing tests; (d) no scope creep
> or unrelated changes. Return a verdict `APPROVE` or `REJECT` with specific,
> actionable findings.

## Escalation & reporting

- **On cap exhaustion or a blocked test-lock conflict:** set status `blocked`,
  write the failure report into the ticket file, and ask the user how to proceed.
  Do not silently continue to the next ticket if it depends on the blocked one.
- **After each ticket:** brief status line (ticket id, ready-for-merge, branch,
  test summary). **At the end:** the full stacked-branch chain for the user to
  review/merge, and any blocked tickets.

## Definition of done (per ticket)

All of: (1) orchestrator's tests green (verified by you), (2) test files unchanged
from what you authored, (3) reviewer APPROVES, (4) full regression green on the
branch → status `ready-for-merge`, then **pushed to `origin` AND its merge request
opened** (title = the feature commit subject, description = the FLATTENED ticket `.md`,
target = `main`, `remove_source_branch=false`; a stacked ticket also declares its merge
prerequisite) via the Step 6 push-options command. Only the human merges (in the GitLab GUI).

## What this skill does NOT do

- No parallel tickets. No auto-merge to the base branch. No editing tests by the
  implementer. No infinite loops. No non-coding tasks.

## Resumability

Ticket files carry `status` + `attempts`, so a re-invocation can resume: skip
`ready-for-merge` tickets, continue `blocked`/in-progress ones from their branch.
