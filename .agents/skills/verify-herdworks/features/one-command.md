# One command to a verified branch (hw run)

Sub-features: `hw run` (create, drive, end state), `hw status TASK [--json]`, `hw watch`, per-task
`--max-minutes` / `--max-tokens` budgets, the Project `webhook`, `--resume`, `--detach`, and
`hw say` refusing a message that names a closed or unknown task.

User entry: `hw run -p PROJECT "request"` after `hw project add`; no coordinator, no `hw say`.
Source: [drive.py](../../../../herdworks/drive.py) (the loop), [monitor.py](../../../../herdworks/monitor.py)
(status record, budgets, webhook), [tokens.py](../../../../herdworks/tokens.py) (agent token counts),
`route` in [talk.py](../../../../herdworks/talk.py).

Harness: `journey.py one-command --project NAME --evidence ABS_PATH` in the scratch core, with real
opencode/deepseek-flash workers for build, verify and evidence. It runs four parts in order:

1. `hw run --file briefs/shout.md` as a subprocess. While it runs the journey samples
   `hw status HE-1 --json` every 8 seconds and runs `hw watch HE-1` beside it. Required: exit 0,
   `done` / `verified`, commit equal to `refs/heads/hw/HE-1`, a fresh `hw gate` VERIFIED, no pull
   request and both missing grants named, no coordinator session, empty inbox, no worker left alive,
   and one builder, one or two verifiers and one evidence review in that order.
2. `hw run --max-minutes 0.15` and `hw run --max-tokens 1` on two more tasks. Required: exit 2,
   `blocked` with the budget as the reason, the resume command as next step, no live worker, and one
   webhook payload each with `"event": "budget"` at the journey's own 127.0.0.1 listener.
3. `hw run --resume HE-2 --max-minutes 30 --detach`, then `hw watch HE-2`. Required: exit 0, verified,
   the killed builder replaced exactly once.
4. `hw task close HE-1`, then `hw say` naming HE-1 in the text, with `--task HE-1`, with
   `--task HE-99` and with `--task HE-2` (finished). Required: each exits 1 naming the reason and
   the next step, the inbox stays empty and no coordinator starts.

Evidence: `transcript.md` (every owner command, its output and exit code, then the check list),
`run.txt`, `watch.txt`, `status-samples.jsonl`, `webhook.jsonl`, `final-HE-1.json`,
`blocked-HE-2.json`, `blocked-HE-3.json`, `final-HE-2.json`, `checks.json`, `result.json`, the
task folders and `cleanup.json`. Read `checks.json` and the samples yourself; `result.json` alone
is not the proof.

Gotchas:
- Token counts come from opencode's own session database for the worker's folder, so they need the
  real `~/.local/share/opencode` that `bin/hw-opencode` points opencode at. A different agent that
  keeps no readable count shows `unknown`; that is correct, not a failure.
- A second verifier is not a failure. When the first one's `claims.json` is unusable (seen live: an
  `evidence` value listing several files), the gate would refuse it, so `hw run` starts one more
  verifier, as the coordinator's rule 30 does. A fix round (a second builder in part 1) is a failure.
- The 0.15 minute budget is short on purpose: the builder must be killed before it commits, or the
  resume in part 3 stops with "builder branch advanced without a complete report".
- The webhook URL carries a token in its query string. The journey fails if that token or the
  listener's port appears in any task record, status or transcript.
- Not covered live: opening a draft pull request from `hw run` (no remote here; `tests.test_run`
  covers the branch with a stand-in, `draft-pr` covers `hw pr` itself), a builder's BLOCKED question
  answered through `hw say --task`, fix rounds and escalation (all in `tests.test_run` with fake
  agents), and Codex token counts (reader unit-tested against the real table shape only).
