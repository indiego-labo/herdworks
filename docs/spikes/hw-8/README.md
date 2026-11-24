# HW-8 live verification follow-up

Candidate `d230e7aafe4f688cd85f6e7811f790e248c9632e` was exercised in the original
macOS builder run and the independent agent-dev Linux verification. The HW-6
`verify-3/verdict.md` remains **INCONCLUSIVE** and `evidence-1/review.md` remains
**CONFIRMED** for the evidence it inspected.

**Call: NO-GO for closing all HW-6 live verification gaps.** The independent Linux GO
covers the essential Bot-to-Project delivery and owner correction with a deterministic
coordinator. Model-backed worker startup and prompt handling remain open. These findings
add no condition to ready-for-review publication or the opt-in merge follow-up.

## Independent Linux follow-up

The Project retains the raw artifacts under HW-8's `verify-1/evidence/`.
The SSH runner, candidate archive identity, exact command output and zero diff outside
the spike are in `commands.json`. This section describes that run. The macOS builder run
below has its own traces.

| Check | Grade | Command and observed evidence under `verify-1/evidence/` |
| --- | --- | --- |
| Numbered delivery, acknowledgement and assessment | PROVED with a coordinator fixture | `owner-journey.py` intake ran `hw say verify`, `hw task new verify --message 1` and `hw wait verify`. Real herdr carried the original multiline text. The fixture acknowledged IV-1 and the inbox, task, tasks and status showed yellow impact with a reason, unreproduced and low confidence. See `agent-dev/{ac1.txt,owner-commands.jsonl,coordinator-pty.jsonl,inbox.jsonl,ack-1.txt,initial-task.json,tasks-initial.txt,status-initial.txt}`. |
| Update and replay | PROVED | The runner updated IV-1 and repeated `hw say verify --number 1`. It got an acknowledgement for the same task, one inbox entry for message 1 and the updated assessment. Replay with altered metadata was refused. See `agent-dev/{ac2.txt,ack-repeat.txt,updated-task.json,replay-mismatch.txt,inbox.jsonl}`. |
| Owner correction and gate | PROVED | `hw task correct-impact verify IV-1` was denied in the labelled terminal and accepted by the SSH owner. A later proposal was refused and an explicit reset persisted. The two gate refusals matched byte for byte and publishing was refused for absent scratch grants. See `agent-dev/{ac3.txt,terminal-commands.jsonl,owner-commands.jsonl,corrected-task.json,owner-reset-task.json,gate-before.txt,gate-after.txt,pr-denied.txt}`. |
| Legacy intake | PROVED | The no-flags `hw say verify` produced message 2 and IV-2 with no assessment field. See `agent-dev/{ac4.txt,ack-legacy.txt,legacy-task.json,tasks-with-legacy.txt}`. |
| Legacy template launch | PROVED | `hw spawn verify IV-2 build` created the live `hw-builder` terminal and task worktree. See `agent-dev/{legacy-spawn.txt,worker-session.txt,tasks/IV-2/events.jsonl}`. |
| Legacy adapter and argument parsing | PROVED | The real candidate `hw-codex worker` prepared the worker arguments. The fixture invoked the installed Codex executable as `codex --help` with those same arguments and exit 0. See `agent-dev/{processes.jsonl,builder-cli.jsonl}` and `codex-fixture.py`. |
| Legacy automatic prompt delivery | PROVED with a worker fixture | The fixture reported herdr status and received the first message addressed to the generated brief. The spawn and launch event both record `sent: true`. See `agent-dev/{legacy-spawn.txt,builder-pty.jsonl,tasks/IV-2/build-1/brief.md}`. |
| Model-backed Codex startup | NOT_PROVED | The builder protocol forbids starting another agent, including a Codex worker in a scratch core. The independent trace contains help-parser invocations. It leaves real Codex session initialization, authentication, sandbox startup and readiness reporting open. See `agent-dev/builder-cli.jsonl` and the [worker evidence check](check-worker-evidence.py). |
| Model-backed Codex prompt handling | NOT_PROVED | The same prohibition prevents a real worker turn. The fixture consumed the first PTY prompt. The trace leaves Codex reading and acting on the brief and completing the build with a task-branch commit and matching READY report open. See `agent-dev/{builder-pty.jsonl,worker-probe.txt,legacy-gate.txt}`. |
| Linux unit suite and macOS limits | PROVED for the 252 Linux-runnable tests | `python3 -m unittest discover -s tests -v` ran 259 tests with seven macOS skips, exit 0. The portable refusal when the OS sandbox is absent passed. The independent macOS probe was denied at `sandbox_apply`. That run left the seven checks in AC-8 through AC-14 open: forged override evidence and verdict, verifier hooks, override builder commits, gate replacement, rejected sandbox profiles and override write/network confinement. See `agent-dev/unit-suite.txt`, `macos-sandbox-probe.txt` and the retained `verify-1/claims.json`. |
| Disposable scope and cleanup | PROVED | `python3 ../evidence/check-artifacts.py` confirmed the three private attempts removed their owned terminals, worktrees and cores, and that the remote scratch directory was removed. Read-only default-core snapshots preserved the existing addresses. See `retained-artifacts.txt`, `remote-cleanup.txt` and `agent-dev/{cleanup.json,core-stop.txt,fixture-worktrees-after.txt}`. |

Replay the worker evidence check with the retained evidence directory:

```sh
python3 docs/spikes/hw-8/check-worker-evidence.py /path/to/verify-1/evidence
```

The checker reads the saved traces. It correlates the spawn, adapter process, installed
CLI invocation, fixture prompt and generated brief. A live follow-up would require a
coordinator-authorized real worker session on a private core with the normal launcher,
an authenticated Codex installation and a disposable repository. Capture readiness and
automatic prompt receipt, then inspect the worker's commit and matching READY report.
The deterministic coordinator's acknowledgements also leave autonomous coordinator
handling outside this proof.

## Original macOS builder findings

| Check | Grade | Observation and evidence |
| --- | --- | --- |
| Numbered transport, acknowledgement and stored assessment (HW-6 AC-1) | PROVED for real transport and a deterministic coordinator | `hw say live … --impact yellow --impact-reason 'Requires a production migration' --reproduction unreproduced --confidence low` returned `delivered 1`. The labelled PTY received `MESSAGE 1` and the unmodified request text. Its receiver ran `hw task new live --message 1` and wrote the numbered `REPLY`. `hw read live` returned the reply naming `LV-1`. The inbox, initial task and both status views retained the four fields. Replay delivered the same payload, acknowledged the same task and left a single task for message 1. [Commands](evidence/commands.jsonl), [PTY input](evidence/pty-delivery.jsonl), [inbox](evidence/inbox.jsonl), [initial task](evidence/initial-task.json), [replies](evidence/outbox/) |
| Real owner correction (HW-6 AC-6) | PROVED | `hw task correct-impact live LV-1 red --reason 'Needs Architect' --confidence high` ran from the owner shell with real process lookup and exited 0. A correction attempt from the labelled receiver exited 1. Replay retained red, unreproduced and high in both status views. A later proposal was refused. `hw gate` returned the same refusal before and after correction, the PR command refused absent grants both times and `project.json` stayed byte-identical. [Owner commands](evidence/commands.jsonl), [coordinator commands](evidence/coordinator-commands.jsonl), [corrected task](evidence/corrected-task.json) |
| Legacy launch up to the Codex executable (HW-6 AC-8) | PROVED with a worker fixture | The flagless request produced `LV-2` without an impact field and with the original brief text. `hw spawn live LV-2 build` created the real worktree and a child herdr terminal using the installed `hw-builder` template and candidate `hw-codex worker`. The executable at the Codex boundary was a deterministic fixture. Because it reported no agent status, automatic first delivery returned `sent: false` and `hw spawn` exited 1. An explicit `hc send t2 'Read …/build-1/brief.md in full and do what it says.'` delivered the task prompt to that terminal. The fixture opened the brief and `hw probe live LV-2` exited 0 inside that terminal. [Spawn and probe](evidence/coordinator-commands.jsonl), [launch event](evidence/worker-event.jsonl), [process](evidence/worker-process.jsonl), [PTY input](evidence/worker-input.jsonl), [brief and probe](evidence/worker-probe.jsonl), [legacy task](evidence/legacy-task.json) |
| Full unit regression (HW-6 AC-12) | PROVED on macOS | `python3 -m unittest discover -s tests -v` ran all 259 tests with exit 0, including the launch isolation, hook isolation and verifier/evidence override checks that previously hit nested sandbox restrictions. [Unit transcript excerpt](evidence/unit-summary.txt) |
| Disposable scope and cleanup | PROVED | The only Project and worktree were scratch fixtures. No publishing or unsandboxed grant was enabled. The final terminal list was empty, only the base fixture Git worktree remained, the pinned candidate was clean, and the core and scratch directory were removed. [Cleanup](evidence/cleanup.json), [command trace](evidence/commands.jsonl), [lifecycle](evidence/lifecycle.txt) |

## Host boundaries

The numbered herdr transport, task state, owner check and ordinary Codex launch path are portable checks. Successful owner correction needs permission to execute `ps` and enumerate the process ancestry. Live transport needs a functioning herdr terminal holder. Those were restrictions of the earlier verifier’s shell. The `--role` process isolation, nested sandbox application, protected resources and forged override unit tests exercise macOS `sandbox-exec`. Linux can check refusal when that platform safeguard is unavailable and can exercise the ordinary worker path with its own launcher configuration.

In the original builder run, the SSH connectivity probe identified agent-dev as Linux and found its installed herdr and Codex. The automatic approval review rejected the command that would transfer a Git bundle and proof scripts and execute them on that host. The proof ran locally in a disposable core outside the restricted shell. The independent Linux run above followed that builder run.

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
