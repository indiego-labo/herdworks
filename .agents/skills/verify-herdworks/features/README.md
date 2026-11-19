# Herdworks verification map

Current Project recipes are in [FP-1 Project coverage](#fp-1-project-coverage) below.
The fh-* sections retain historical reports and use the helpers from those commits.

| Feature | Journey | Expected artifact | State |
| --- | --- | --- | --- |
| [Built run](built.md) | built | READY/head/catchup agree; status built | Proven 2026-11-15 |
| [Decision boundary](blocked.md) | blocked-builder | BLOCKED, ask, waiting; no new commit | Proven 2026-11-15 |
| [Lead sandbox](sandbox.md) | lead-cannot-write | Worker and shared temporary writes denied; tool-created worker | Fix round 1; independent verification pending |
| Regression | regression plus cleanup from each journey | main/head compile; foreign terminals preserved | Proven 2026-11-15 |

Evidence is saved by the caller, normally under evidence/plan-01/FH-1/.
A driver's independent verdict remains separate from this builder's proof.

Builder proof on 2026-11-15: evidence/plan-01/FH-1/{built,blocked-builder,lead-cannot-write,regression}/.
All three live journeys passed and cleanup preserved baseline terminals with none owned left.
The built journey also records unattended observations and review media in ../unattended/ and ../review/
relative to those evidence directories. This is producer proof; the driver supplies the independent verdict.
The first built attempt failed on launcher flags, was retained as built-attempt-1 and cleaned before the corrected rerun.

Independent verification of d618e11 found that the original sandbox journey missed writable
system temporary roots from a home checkout. Fix round 1 adds those probes and private temporary
storage for both modes. Its diagnosis and builder proof are in evidence/plan-01/FH-1/fix-round-1/.
The driver owns the fresh independent verdict.

## FH-2 coverage

| Feature | Journey | Expected artifact | State |
| --- | --- | --- | --- |
| Independent verification and evidence gate | verified | PASS, CONFIRMED, VERIFIED and verified status at one SHA | Builder proof passed 2026-11-15 |
| Rejected wrong build | planted-fail | real FAIL, no evidence reviewer, REFUSED, ask and waiting | Builder proof passed 2026-11-15 |
| Independent brief | brief-isolation from planted-fail | brief.md excludes BUILDER-SAYS-IT-WORKS | Builder proof passed 2026-11-15 |
| Worker cleanup | cleanup from verified | no verifier worktree; only lead live; evidence retained | Builder proof passed 2026-11-15 |

Evidence lives under evidence/plan-01/FH-2/. The hello CLI, git, hc and all Codex sessions
are real. planted-fail replaces only the builder with a versioned plain program. The FH-2
builder runs verified and planted-fail once each and inspects coverage; the driver owns
independent verification of FH-2 and its parent/head regression runs. No FH-3 fix,
replacement or answer/resume/stop behavior is claimed.

FH-2 builder evidence: verified/, planted-fail/, brief-isolation/ and cleanup/ under
that evidence root. verified passed on its corrected rerun; verified-attempt-1/ preserves
product success followed by a harness assertion failure because hc ls omits labels. The
assertion now uses recorded session names. Both final journeys exited zero, retained raw
proof, removed owned sessions and preserved baseline terminals. 40 unit tests passed.
The regression helper accepts --base FH1_SHA and runs built and blocked-builder at that
commit and head; this expanded regression recipe is for the driver and was not live-run
by the FH-2 builder. Independent FH-2 verification remains pending with the driver.

Regression recipe component proof uses real git and substitute journey programs; it checks
parent/head selection and worktree cleanup, not actual parent/head agent behavior.

## FH-2 fix 1

The accepted override finding is fixed: every session records template versus override
launch provenance. The gate requires template provenance for both verification roles;
status retains override labels after sessions exit. README and unit coverage describe
the boundary. Missing provenance in older event logs is refused rather than trusted.

Real parent/head regression is now proven under evidence/plan-01/FH-2/regression/fix-1/.
The regression --base fh-1 command exited 0 with all four real-agent journeys passing:
parent-built, parent-blocked-builder, head-built and head-blocked-builder. The fixed
working tree's build reached verified with real verifier/evidence-reviewer template
sessions. Both decision cases retained the base commit and asked one question. Cleanup
preserved baseline terminals, removed owned workers and removed the parent checkout.
This supersedes the previously pending real regression above; no regression code change
was needed. The source-under-test patch is in evidence/plan-01/FH-2/fix-1/.

## FH-3 coverage

| Feature | Journey | Required outcome | Proof state |
| --- | --- | --- | --- |
| Diagnose and fix | fix-round | new builder/diagnosis/new SHA/fresh PASS/verified | Builder proof passed 2026-11-15 |
| Three-fix cap | round-cap | four builds/four FAILs/ask | Builder proof passed 2026-11-15 |
| Ask and answer | external-prerequisite | INCONCLUSIVE/Cause/Ask, archived installed answer, verified without fix | Builder proof passed 2026-11-15 |
| Stall replacement cap | stalled-session | two screens/stalled events, three verifiers, waiting/no fix | Builder proof passed 2026-11-15 |
| Slow progress | slow-worker | nine writes, one verifier, no stalled event | Builder proof passed 2026-11-15 |
| Cold pickup | pickup | new lead, no rebuilt artifact, verified | Builder proof passed 2026-11-15 |
| Stop | stop | labelled sessions ended, stopped status | Builder proof passed 2026-11-15 |
| FH-2 regression | regression --base FH2_SHA | parent/head verified and first planted FAIL | Driver proof pending |

The planted verifier journeys end at timing/failure outcomes and never claim verified.
The external prerequisite is installed by the harness as a simulated user action; all Codex,
hc, git, CLI and gate behavior is real. Evidence belongs under evidence/plan-01/FH-3/.
Independent verdict and review remain with the driver. Unit tests additionally cover crashes
between setup mutations, atomic branch claims and expected-value rollback deletion.

FH-3 producer evidence is complete under evidence/plan-01/FH-3/: fix-round/,
external-prerequisite/, stalled-session/, pickup/, stop/, slow-worker/ and round-cap/.
Each journey ran once and passed its assertions. Each cleanup.json records preserved
baseline terminals and no owned terminals remaining. final-terminals.json records only
the original FH-3 builder after every outer journey terminal was removed.

The final unit suite has 70 passing tests, including interrupted retry/replacement/resume,
branch claim/CAS deletion, incomplete diagnosis reports, fresh-answer boundaries, rewind,
and the existing provenance gate. Review media in review/ includes waiting-status.png,
ask.png and ask-and-resume.mp4 (45 seconds). The video holds actual CLI excerpts for
readability; source capture timestamps remain in screens.json and provenance.json.

The prerequisite run exposed a resolved ask note masking a passing gate. Its before-status
and resolved note are retained; restoring gate-before-ask precedence made that same real
run verified. All timing journeys retain the override provenance restriction: their planted
verdicts cannot pass the gate. Producer proof is not an independent verdict at the final
commit; the driver owns final-head verification and parent/head regression.

## FP-1 Project coverage

The sections above describe historical proof on the fh-* commits. Use those commits' helpers
for their historical command interfaces. The current helper uses Projects, numbered messages
and task ids; it replaces the one-task coordinator lifecycle while retaining worker/gate rules.

| Feature | Journey | Required outcome | Proof state |
| --- | --- | --- | --- |
| Persistent coordinator and task gate | converse | reply within 60 seconds; PASS/CONFIRMED/VERIFIED/DONE at one SHA | Producer PASS: converse/ |
| Never busy | converse, status message during build | numbered status REPLY before builder report exists | Producer PASS: never-busy/ |
| Remembers | converse, "that one" after DONE | REPLY names HE-1 without a new task | Producer PASS: remembers/ |
| Product question and answer | question-and-answer | one QUESTION, waiting on you, no commit, answer through say, verified | Proven real outcomes; corrected assertion: question-and-answer/result-supplement.txt |
| Fresh fix round | fail-and-fix | first FAIL, fresh builder/diagnosis/new SHA, verified | Producer PASS: fail-and-fix/ |
| Coordinator pickup | pickup | killed during verification, up, no second build, verified | Producer PASS: pickup/ |
| Stop a task by message | stop | stopped status, no live workers, coordinator alive, catchup.md and DONE | Producer PASS: fix-round-1/stop-rerun/ |
| Replay | repeat-message | repeat reply, one task, verified | Producer PASS bundled with pickup: repeat-message/ |
| Parent comparison | regression --base FH3_SHA | parent's verified and head's converse agree on correct CLI/gate | Driver proof pending |
| Storage and message boundaries | unit suite | external home, validation, counters, replay, blocked/send and outbox checks | 86 unit tests passed; see unit/unittest.txt |

Evidence belongs under evidence/projects/FP-1/. Each corrected attempt has a new evidence
folder. The driver owns Herdworks' independent verdict and evidence review at its final head.
The real fixture agents use the Project's normal gate; their verdicts prove the fixture task,
not independent verification of Herdworks implementation. Timed screens include a post-gate
last frame; render tasks and QUESTION screenshots plus a 30–60 second converse video.

Producer proof completed 2026-11-15. Converse includes never-busy and remembers on its own
Project. Question-and-answer reached VERIFIED after one evidence repair; its original helper
then selected a later reply due to glob ordering. That assertion is fixed and rechecked using
the same real records; the original nonzero result and positive supplement are both retained.
Fail-and-fix and pickup exited zero. Pickup includes the optional replay check; standalone
repeat-message was not additionally run. Final cleanup shows only original t7 and t78, with
all owned sessions removed. Review media includes tasks.png, question.png and a 45-second
converse.mp4 whose final capture is after a passing gate. Parent/head regression and the
independent final-head verdict remain with the driver.


## FP-1 fix round 1

Producer evidence is under `evidence/projects/FP-1/fix-round-1/`. The accepted authorization,
startup delivery, unsent startup, Project publication and doctor findings each have a
failing-before test in `red-tests.txt` and passing checks in `green-tests.txt`. The final
suite passes 96 tests in `unit-final.txt`. `boundary-live.json` records the real hc exec
hop from a labelled coordinator: foreign say, task creation and stop refused without
changes, while its own task creation succeeded. Launch failure injection uses a mock
transport; normal Herdworks messaging, agents, sandboxes and Git in the journeys are real.

`stop-rerun/` passes the full stop contract, including live builder before the request,
no live task workers afterward, live coordinator, nonempty catchup and numbered DONE.
The coordinator's existing stop rule already produced both artifacts. The first attempt
in `stop/` passed its product assertions but its cleanup presence check failed when the
concurrent FP-2 run removed its own sessions. Its raw cleanup and explanatory note remain.
Cleanup now refuses baseline targets and records unrelated disappearance separately;
`cleanup-red.txt` and `cleanup-green.txt` prove that behavior. Unique --project names avoid
colliding with another journey's session names.

`converse/` passes with real PASS, CONFIRMED and VERIFIED at the same fixture commit,
DONE naming that commit, a status reply preceding the build report and a later reply
remembering HE-1. Its CLI output is checked directly. Both passing journey cleanups
leave no owned sessions and never target baseline terminals. Converse also records t8g
and t8j disappearing during another owner's cleanup; foreign_untouched remains true. A further unit regression in
`recovery-red.txt` exposed new-message omission after ready startup reconciliation;
`recovery-green.txt` proves that reconciliation still sends the new message while a
fresh startup consumes the saved inbox once.

This is producer proof on hello. The driver owns independent Herdworks verification and
review at the final head; no additional verifier or reviewer agent was started for Herdworks.

## FP-2 draft pull request coverage

| Feature | Journey | Required outcome |
| --- | --- | --- |
| Grants and current gate | tests.test_pr | each grant and gate failure prevents push and gh |
| Verified draft | draft-pr | local bare branch at verified SHA; one fake gh pr create --draft; four sections, verifier commands/output and CONFIRMED; DONE URL; tasks for review |
| No grant | no-grant | no pushed refs or gh calls; DONE says not opened and names missing grants; verified commit |
| Duplicate and uncertain creation | tests.test_pr | second creation refused, including interrupted result |
| Safe push | tests.test_pr | no force, hooks disabled, exact verified SHA; changed head prevents draft |
| Parent comparison | driver regression | converse and question-and-answer on FP-1/head remain verified with no grants |
| Real repository | driver only | real unmerged draft at verified SHA; gh pr view evidence and video |

Producer evidence belongs under evidence/projects/FP-2/. Render the actual tasks and PR body
captures to review/tasks.png and review/pr-body.png. This fixture proof substitutes only the
remote repository and GitHub CLI; the coordinator, workers, gate, git push, storage and CLI
are real. It is not Herdworks' independent verdict or the driver's real-repository proof.

## FP-3 journeys
The five FP-3 journeys select opencode and deepseek/deepseek-flash for all four roles,
explicitly grant unsandboxed sessions, and save the effective config and launch provenance.
Run them with unique --project names using the same hc run / hc wait / hc rm lifecycle.
- two-at-once: two independent requests in one numbered message; require both builders alive
  together, distinct branches/worktrees from one base and both independent gates VERIFIED.
- queued: machine max_tasks_at_once=1; retain queued output naming that limit, then require
  the second builder's start after the first passing gate and both VERIFIED.
- memory-carries: first builder records the test command through memory add, second builder
  receives it in its brief; both tasks pass the independent gate.
- verifier-blind: a real opencode builder runs a supplied memory-planting script, then passes
  independent verification. The marker appears in memory and nowhere in either reviewing brief.
- disk-floor: task new and a refused spawn with min_free_disk_gb above actual free space;
  queued output names the floor and no session was started. This admission journey needs no agent.
All opencode sessions are unsandboxed. The launcher's private hc shim restores scratch core
paths for hc commands while opencode alone uses the real provider configuration/sign-in folders.
The helper preserves every attempt; a failed run is not proof. The driver owns parent/head
regression and the independent Herdworks verdict.

## FP-4

| Behavior | Producer proof | Boundary |
| --- | --- | --- |
| Linux sandbox on/off and no planted roles | tests.test_host; start/linux-sandbox.md | Real Codex sandbox baseline; unit launch arguments |
| Remote Project conversation | remote-converse | Real remote hc and opencode/DeepSeek; disposable hello repository |
| Retain records and reclaim worktrees | disk; tests.test_host | Real Git worktree removal and host free-space reading |

The driver owns remote-real-repository, independent verification and parent/head regression.

## FP-6 automations

Run `schedule`, `issue-pickup` and `cap-and-switch` with the ordinary journey command,
unique `--project` names, scratch core and scratch HW_HOME. Each sends a
status-only question through real say and requires a real opencode/DeepSeek REPLY.
No workers or timer installation are needed. GitHub is always the fixture fake-gh.

| Behavior | Proof | Outcome |
| --- | --- | --- |
| Due schedule | schedule | early tick and preview send nothing; due tick sends one message; history records it |
| Issue pickup | issue-pickup | two ticks, one message, exactly one label edit |
| Cap and switch | cap-and-switch | two offered issues then a third while off; one message total |
| Failures, stale ticks, retry, comments | tests.test_automations | PROBLEM/off after three failures or idle; stable message key; PR comment and recovery deduplication |
| Manual tree | tests.test_status | one/all Projects, coordinator, live worker role/agent/status/quiet/attach; closed omitted |

Retain automations/, inbox, outbox, fake-gh.jsonl, CLI text, doctor, result and
cleanup.json under evidence/projects/FP-6/JOURNEY/. Render automations.txt and
history.txt to review/automations.png and review/history.png with scripts/render.py.
The driver's real-issue journey owns the timer installation, real issue, full task
to draft PR and video. These fixture journeys prove pickup/delivery, not that wider
boundary. Parent/head regression and independent Herdworks verdict also stay with
the driver. Never call real gh or enable the supplied timer in fixture proof.

## FP-7 manual verification

`environment-blocked` reuses the real Project journey on opencode/DeepSeek, a local
bare remote and fake gh. The fixture's CLI/tests can pass, but its external
HelloBoard check requires the genuinely absent hello-device-probe tool/device.
No stand-in is provided for that missing environment capability. All other agents,
Git, gate checks and message/PR mechanics are real; GitHub is the stand-in only.

Require one build, one verifier with INCONCLUSIVE/BLOCKED-BY-ENVIRONMENT and proof
that all other checks passed, an evidence inspection, a REPLY identifying the
missing tool and proven checks, one draft with [Needs manual verification], the
blocker section and label, and tasks needs manual verification with its URL.
The normal gate must remain REFUSED. Preserve manual-handoff.json, environment.json,
CLI output, draft body, fake-gh log, events, artifacts, messages and cleanup.
The driver owns parent/head draft-pr regression, a real task on the remote host and independent
Herdworks verification. Never call real gh, merge, or mistake this partial handoff
for a VERIFIED task. Existing draft-pr remains the strict gate regression recipe.

## One command (hw run)

| Behavior | Proof | Outcome |
| --- | --- | --- |
| [One command to a verified branch](one-command.md) | one-command part 1 | exit 0, done/verified at the branch head, fresh gate VERIFIED, no coordinator, no nudge |
| Live status and watch | one-command part 1 | samples show stage, rising elapsed, agent-reported tokens and last action while running; watch ends on done |
| Budgets and webhook | one-command part 2; tests.test_run | max_minutes and max_tokens stop workers, blocked with reason, `budget` payload at a local listener; URL never recorded |
| Resume and detach | one-command part 3 | blocked task continues detached with its printed next step and ends verified |
| Messages naming a closed or unknown task | one-command part 4; tests.test_run | refused with reason and next step; nothing recorded |
| Fix rounds, escalation, builder question, dead worker, draft pull request, Codex tokens | tests.test_run | fake agents and stand-ins only; not live |

Evidence belongs under the caller's evidence root in `one-command/`. This is producer proof on the
hello fixture with real opencode workers; an independent verdict for Herdworks stays with the driver.
