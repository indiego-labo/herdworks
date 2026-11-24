# HW-8 live verification follow-up

Candidate `d230e7aafe4f688cd85f6e7811f790e248c9632e` was run from a clean, detached checkout on owner-capable macOS. The earlier HW-6 `verify-3/verdict.md` remains **INCONCLUSIVE** and `evidence-1/review.md` remains **CONFIRMED** for the evidence that review inspected. This spike adds observations for the same candidate.

**Call: NO-GO for closing all of HW-6’s live verification gaps.** Real terminal delivery and owner-shell correction worked. The legacy worker reached the Codex launch boundary and read the brief through a fixture. A model-backed coordinator and an existing model-backed worker still need a live check. This finding does not add a condition to ready-for-review publication or the opt-in merge follow-up.

## Findings

| Check | Grade | Observation and evidence |
| --- | --- | --- |
| Numbered transport, acknowledgement and stored assessment (HW-6 AC-1) | PROVED for real transport and a deterministic coordinator | `hw say live … --impact yellow --impact-reason 'Requires a production migration' --reproduction unreproduced --confidence low` returned `delivered 1`. The labelled PTY received `MESSAGE 1` and the unmodified request text. Its receiver ran `hw task new live --message 1` and wrote the numbered `REPLY`. `hw read live` returned the reply naming `LV-1`. The inbox, initial task and both status views retained the four fields. Replay delivered the same payload, acknowledged the same task and left a single task for message 1. [Commands](evidence/commands.jsonl), [PTY input](evidence/pty-delivery.jsonl), [inbox](evidence/inbox.jsonl), [initial task](evidence/initial-task.json), [replies](evidence/outbox/) |
| Real owner correction (HW-6 AC-6) | PROVED | `hw task correct-impact live LV-1 red --reason 'Needs Architect' --confidence high` ran from the owner shell with real process lookup and exited 0. A correction attempt from the labelled receiver exited 1. Replay retained red, unreproduced and high in both status views. A later proposal was refused. `hw gate` returned the same refusal before and after correction, the PR command refused absent grants both times and `project.json` stayed byte-identical. [Owner commands](evidence/commands.jsonl), [coordinator commands](evidence/coordinator-commands.jsonl), [corrected task](evidence/corrected-task.json) |
| Legacy launch up to the Codex executable (HW-6 AC-8) | PROVED with a worker fixture | The flagless request produced `LV-2` without an impact field and with the original brief text. `hw spawn live LV-2 build` created the real worktree and a child herdr terminal using the installed `hw-builder` template and candidate `hw-codex worker`. The executable at the Codex boundary was a deterministic fixture. Because it reported no agent status, automatic first delivery returned `sent: false` and `hw spawn` exited 1. An explicit `hc send t2 'Read …/build-1/brief.md in full and do what it says.'` delivered the task prompt to that terminal. The fixture opened the brief and `hw probe live LV-2` exited 0 inside that terminal. [Spawn and probe](evidence/coordinator-commands.jsonl), [launch event](evidence/worker-event.jsonl), [process](evidence/worker-process.jsonl), [PTY input](evidence/worker-input.jsonl), [brief and probe](evidence/worker-probe.jsonl), [legacy task](evidence/legacy-task.json) |
| Model-backed worker and autonomous coordinator response | NOT_PROVED | The builder protocol forbade starting agents. The receiver supplied the coordinator decisions and acknowledgement. The worker fixture exercised the command and brief path. Herdr's automatic delivery handshake with a status-reporting agent, the agent's understanding of the brief, and completion of the worker protocol through a real commit and READY report remain open. The intake assessment itself was supplied as CLI arguments. [Terminal fixtures](terminal-fixture.py), [transport and launch commands](journey.py) |
| Full unit regression (HW-6 AC-12) | PROVED on macOS | `python3 -m unittest discover -s tests -v` ran all 259 tests with exit 0, including the launch isolation, hook isolation and verifier/evidence override checks that previously hit nested sandbox restrictions. [Unit transcript excerpt](evidence/unit-summary.txt) |
| Disposable scope and cleanup | PROVED | The only Project and worktree were scratch fixtures. No publishing or unsandboxed grant was enabled. The final terminal list was empty, only the base fixture Git worktree remained, the pinned candidate was clean, and the core and scratch directory were removed. [Cleanup](evidence/cleanup.json), [command trace](evidence/commands.jsonl), [lifecycle](evidence/lifecycle.txt) |

## Host boundaries

The numbered herdr transport, task state, owner check and ordinary Codex launch path are portable checks. Successful owner correction needs permission to execute `ps` and enumerate the process ancestry. Live transport needs a functioning herdr terminal holder. Those were restrictions of the earlier verifier’s shell. The `--role` process isolation, nested sandbox application, protected resources and forged override unit tests exercise macOS `sandbox-exec`. Linux can check refusal when that platform safeguard is unavailable and can exercise the ordinary worker path with its own launcher configuration.

The SSH connectivity probe identified agent-dev as Linux and found its installed herdr and Codex. The automatic approval review rejected the command that would transfer a Git bundle and proof scripts and execute them on that host. The proof ran locally in a disposable core outside the restricted shell. Linux runtime behavior on this candidate remains untested.

## Reproduce the owner-shell proof

From this repository, use an owner-capable shell with Git, herdr, Python 3.11+ and Codex on PATH. The runner reads a bundle and the two proof scripts from stdin and writes a tar of the evidence to stdout. Its scratch core uses a unique session, empty XDG paths and a fresh Herdworks and Codex home. The core’s `codex` resolves to the fixture. The real Codex executable is queried only for its version.

```sh
code="$PWD/docs/spikes/hw-8"
input=$(mktemp -d)
git bundle create "$input/candidate.bundle" HEAD
mkdir "$input/evidence"
tar -cf - -C "$code" journey.py terminal-fixture.py -C "$input" candidate.bundle |
  bash "$code/run-owner.sh" > "$input/evidence.tar" 2> "$input/host.log"
tar -xf "$input/evidence.tar" -C "$input"
```

The bundle must contain the pinned candidate. The runner checks it out by full commit id. The raw transcripts and earlier attempts are preserved alongside the builder report. The committed unit transcript is an excerpt. The other committed traces and state files are copied from the final attempt.
