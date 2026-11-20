---
name: verify-herdworks
description: Exercise Herdworks Project conversations with real coordinator, builder, verifier and evidence reviewer sessions in a scratch herdr core; collect artifacts, terminal media and cleanup proof.
---
## Launch and doctor
Requires Python 3.11, git, hc and ffmpeg. Older journeys use Codex login; FP-3 uses opencode login. No Python dependencies.
Use an already running scratch core: non-default HC_SESSION and scratch XDG_CONFIG_HOME,
XDG_STATE_HOME and XDG_RUNTIME_DIR. Set HW_HOME to an absolute scratch directory outside
the checkout. Never use the user's core or ~/.herdworks. The doctor requires all three absolute
scratch XDG paths and refuses their real defaults and a Herdworks home inside the checkout.
Run `python3 .agents/skills/verify-herdworks/scripts/journey.py doctor` and inspect its identity.
Install with `bin/hw install`. It refuses foreign or edited templates. Only in a scratch
core whose templates belong to this test, remove stale hw-*.md and .hw-install.json
before the initial install. Never delete foreign templates to bypass the check.

## Drive
Run sequentially with a new absolute evidence directory for every attempt:
`python3 .agents/skills/verify-herdworks/scripts/journey.py converse --evidence /ABS/evidence/converse`
Inside Codex's sandbox start slow journeys through `hc run --bg --no-notify --no-parent`, then
use `hc wait NAME --timeout 45 --json` and `hc read NAME`. Fixture Git and OS sandboxes need
that outer process. Never launch a duplicate to recover a timeout. The default deadline is
900 seconds; --timeout changes it. The helper waits with hc wait and never sleeps.
Each journey gets its own Herdworks home beneath the supplied scratch HW_HOME, named from
its evidence directory. It makes a fresh committed copy of fixtures/hello and a Project hello. Use --project NAME
with a unique scratch name when another journey shares the core; task ids still start at HE-1.
A first-message sent flag is required. Ordinary hc send can still encounter its startup guard;
Herdworks retries only the documented failure that says nothing was typed, preserving the number.

Journeys:
- converse: send shout.md, require REPLY within a minute, separate PASS/CONFIRMED, gate VERIFIED,
  DONE naming the commit and tasks verified at that commit. While the builder works send a status
  question; never-busy.json must show its numbered REPLY existed before report.md. After DONE,
  ask about "that one"; require a REPLY naming HE-1. These also cover never-busy and remembers.
- question-and-answer: send ambiguous.md; inspect one QUESTION, waiting on you and no commit.
  Send the actual approved choice "Welcome aboard, Ada!" and require verified. The harness
  supplies this simulated product-owner answer; all messaging, code and verification are real.
- fail-and-fix: substitute only the first builder with planted/apply-wrong.sh in task.json before
  it launches. Remove that override after its report. Require first real FAIL, a fresh builder
  name, diagnosis, new commit, real PASS/CONFIRMED and verified. Inspect its recorded provenance.
- pickup: kill the coordinator while its real verifier is working; call up. Require no second
  builder and verified. The name stays f-hello-coord; addresses change. A killed child without an
  artifact must be replaced by the coordinator, with a new step attempt and no repeated build. After
  DONE, this journey also redelivers message 1 and checks the repeat reply and single task, reusing
  the same Project instead of starting another worker set.
- stop: while the real builder is working, send an order through say to stop HE-1. Require
  stopped tasks output, no live task workers, a live coordinator, nonempty task catchup.md and
  a DONE for the stop message. stop-before.json and stop-after.json retain those observations.
- repeat-message: send number 1 again with say --number 1. Require repeat acknowledgement and
  exactly one task, ending verified. No new inbox entry is allocated for a redelivery.
- draft-pr: use a local bare remote and planted/fake-gh.sh, grant push and draft-pr, send
  shout.md through the real coordinator. Require the remote branch at the verified SHA, one
  pr create --draft with all four body sections and verifier commands/output, DONE with its
  address, and tasks for review. Inspect fake-gh.jsonl, pr-body.md, remote.json and timing.json.
- no-grant: same local remote and stand-in, with both grants off. Require no remote refs, no
  fake-gh call, verified status, and DONE naming both missing grants and the verified commit.
- regression --base FH3_SHA: run the parent's verified journey and this head's converse journey
  in a detached disposable checkout. Driver owns this wider comparison. Historical FH-1/FH-2/FH-3
  journey recipes are available from their commits; the current helper uses the Project API.

## Evidence and interpretation
Inspect the actual done check, QUESTION and CLI output yourself; nonempty prose is insufficient.
Every journey retains inbox, numbered outbox, task metadata/events, all numbered worker briefs,
reports/verdicts/reviews/evidence, coordinator task notes, tasks output, observed statuses, timed
terminal text, direct CLI output, gate output and cleanup.json. Startup failures and partial
attempts retain evidence too. For a verified journey the final screen in screens.json is captured after a fresh gate
call returns VERIFIED; stop instead captures stopped status, DONE and catchup.md. Feature coverage and historical proof are in [features/README.md](features/README.md).
Real boundaries: hc, Codex, sandbox, git, Herdworks CLI and hello. Substitutions: disposable target
repository; one planted builder in fail-and-fix; owner choice in question-and-answer; intentional
coordinator loss in pickup; local bare remote and fake gh in draft-pr/no-grant. This is producer proof on a fixture, not proof of arbitrary repositories
or an independent verdict for Herdworks itself. The driver supplies that verdict separately.

Render actual saved terminal text with `scripts/render.py TEXT.txt SCREEN.png`. Render a 45-second
review video using `scripts/render.py screens.json review/converse.mp4 --duration 45`. The video
compresses captured elapsed time and does not claim real-time playback. Retain its source manifest
and timestamps; its final frame must be after the gate passes. Save screenshots of tasks and QUESTION. For FP-2 render draft-pr/tasks.txt and draft-pr/pr-body.md
to review/tasks.png and review/pr-body.png, and inspect them. The real-repository journey and video
belong to the driver; this helper never touches a real GitHub remote or invokes real gh for FP-2.

## Cleanup
The helper ends/removes only sessions with this Project's labels and cleans its worker worktrees.
cleanup.json must show no owned sessions remain and foreign_untouched is true. Baseline sessions
are never targeted; foreign_missing records any that another owner removed concurrently. It leaves
scratch repositories, Herdworks records and evidence for inspection. After reading its result, remove
the outer journey terminal with `hc kill NAME` (if live) and `hc rm NAME`. Leave no owned session
running. Never stop or restart the shared scratch core. Unit checks from a sandboxed caller:
`hc exec -- python3 -m unittest discover -s tests`.

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

## One command (hw run)

`one-command` needs no coordinator and uses the same lifecycle and scratch rules as the FP-3
journeys (opencode with deepseek/deepseek-flash for every worker role, unsandboxed grant):

```sh
python3 .agents/skills/verify-herdworks/scripts/journey.py one-command \
  --project onecmd --evidence /ABS/evidence/one-command
```

It takes about twelve minutes: one full task under a token budget, two forced budget stops, one
detached resume that is sent an answer while it runs (which adds a builder and a second
verification), and three refused `--task` messages. It starts its own webhook listener on
127.0.0.1 and writes `transcript.md` with every owner command, output and exit code. Inspect
`checks.json`, `status-samples.jsonl`, `answer.json`, `webhook.jsonl` and `cleanup.json`; see
[features/one-command.md](features/one-command.md) for the required outcomes, the boundaries it
does not cover and the gotchas (short budgets, the cache check, when the answer is sent). Cleanup also
removes the detached driver terminal, which is labelled `hwrun=PROJECT:TASK` rather than `hw=`.

## FP-4 remote host

Remote-converse runs on Linux through hc exec --on, with real opencode sessions
and deepseek/deepseek-flash for all four roles, the same configuration as FP-3.
Use the remote host's installation ~/.opencode/bin/opencode by adding its
folder to PATH; never copy credentials. No planted --role overrides run on Linux.
ffmpeg is needed only for rendering media, not the journey doctor or remote run.

Register a separate remote session: `hc machine add remote-host --name remote-host
--session fp4`. Set up absolute scratch XDG_CONFIG_HOME, XDG_STATE_HOME,
XDG_RUNTIME_DIR and HW_HOME on that host, outside its checkout. Use one
unique root such as /tmp/hw-fp4-<id>. Keep HC_SESSION non-default there.
Record the user's terminal list before and after with a read-only invocation of
`env -u HC_SESSION hc ls --all --json` from a plain host shell, outside the scratch
XDG environment. Compare addresses; never target those terminals for cleanup.

Ship a committed branch using scripts/ship-to-host.sh. For scratch installs set
HW_HOST_CONFIG_HOME to the host scratch config path. Remove stale hw-*.md
and .hw-install.json only in that owned scratch template directory before
installing. The script refuses dirty checkouts and does not update agent-run.

Through `hc exec --on remote-host -- bash -lc ...`, export the scratch variables,
put ~/.opencode/bin on PATH, and start the helper on the host with
`hc run --bg --no-parent --no-notify --name fp4-converse -- bash -lc ...`.
The inner command must export the same scratch variables and run:

```sh
python3 .agents/skills/verify-herdworks/scripts/journey.py remote-converse \
  --project remotehello --evidence /ABS/evidence/remote-converse
```

Use separate hc exec calls with those scratch variables to wait (at most 45
seconds per call), get and read the outer terminal. Background children of hc exec
alone die on return; never start a duplicate after a wait timeout. Remote-converse
uses the full converse done checks, grants unsandboxed sessions, records sandbox
off, and retains task worktrees after removing owned sessions. Inspect DONE,
VERIFIED, real CLI output, config.txt, task events and cleanup.json. It is fixture
proof, not real-repository proof. The driver owns remote-real-repository and parent/head regression.

Then, in the same scratch environment, run:

```sh
python3 .agents/skills/verify-herdworks/scripts/journey.py disk \
  --project remotehello --converse-evidence /ABS/evidence/remote-converse \
  --evidence /ABS/evidence/disk
```

Disk invokes task close, requires no closed task worktrees on disk or in Git's
registry, retained task records, and free space within 200 MB of the pre-task
reading. Inspect disk.json. Copy evidence back through hc exec --on (for example
with a tar stream), preserving the host paths in provenance. Finally remove only
the outer terminal you started; confirm both the scratch core and the user's
terminal list are unchanged apart from owned terminals removed. Never stop or
restart either core. Preserve failed attempts and explain any unproven boundary.
