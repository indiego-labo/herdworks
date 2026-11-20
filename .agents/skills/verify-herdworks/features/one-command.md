# One command to a verified branch (hw run)

Sub-features: `hw run` (create, drive, end state), `hw status TASK [--json]`, plain `hw status`,
`hw watch`, per-task `--max-minutes` / `--max-tokens` budgets, token counts without cached input,
the Project `webhook`, `--resume`, `--detach`, `hw say --task` to a running task, and `hw say
--task` refusing a closed, unknown or finished task.

User entry: `hw run -p PROJECT "request"` after `hw project add`; no coordinator, and no `hw say`
until part 3.
Source: [drive.py](../../../../herdworks/drive.py) (the loop), [monitor.py](../../../../herdworks/monitor.py)
(status record, budgets, webhook), [tokens.py](../../../../herdworks/tokens.py) (agent token counts),
`route` and `answer` in [talk.py](../../../../herdworks/talk.py), `answers` and `unheard` in
[runs.py](../../../../herdworks/runs.py).

Harness: `journey.py one-command --project NAME --evidence ABS_PATH` in the scratch core, with real
opencode/deepseek-flash workers for build, verify and evidence. It runs four parts in order:

1. `hw run --max-tokens 1000000 --file briefs/shout.md` as a subprocess. While it runs the journey
   samples `hw status HE-1 --json` every 8 seconds and runs `hw watch HE-1` beside it. Required: exit
   0, `done` / `verified`, commit equal to `refs/heads/hw/HE-1`, a fresh `hw gate` VERIFIED, no pull
   request and both missing grants named, no coordinator session, empty inbox, no worker left alive,
   and one builder, one or two verifiers and one evidence review in that order. Tokens: in every
   sample each session's `total` equals input + output + reasoning, `cached` is the separate sum of
   cache reads and writes, `hw status HE-1` prints `tokens=N cached=M`, the webhook carries the same
   object, and the spent total stays under the budget while spent plus cached exceeds it. That last
   check is what shows the budget ignores the cache: counted the old way, the run would have stopped.
2. `hw run --max-minutes 0.15` and `hw run --max-tokens 1` on two more tasks. Required: exit 2,
   `blocked` with the budget as the reason, the resume command as next step, no live worker, and one
   webhook payload each with `"event": "budget"` at the journey's own 127.0.0.1 listener. The count in
   the token reason must be no higher than the spent total (it is read just before the stop). Plain `hw status PROJECT` must then list both tasks as
   `blocked` with their reason and resume command (the first is `stopped` underneath).
3. `hw run --resume HE-2 --max-minutes 30 --detach`. Once its stage is `verify` or `evidence` the
   journey sends `hw say PROJECT --task HE-2` with one more requirement (a `--wave` flag), then
   `hw watch HE-2`. Required: `say` reports the running task will hand it to a builder; exit 0,
   verified; the killed builder replaced exactly once and no fix round; exactly one further
   builder, started after the answer, whose brief alone quotes it and whose session record lists
   its number; a verifier after that builder and the evidence review last; and the product at the
   verified commit prints `Bye for now, Ada!` for `--wave Ada` and still `Goodbye, Ada!` for
   `--farewell Ada`. `answer.json` records the stage when it was sent and every builder's brief.
4. `hw task close HE-1`, then `hw say --task HE-1`, `--task HE-99` and `--task HE-2` (finished).
   Required: each exits 1 naming the reason and the next step, the inbox holds only the part 3
   answer and no coordinator starts.

Evidence: `transcript.md` (every owner command, its output and exit code, then the check list),
`run.txt`, `watch.txt`, `status-samples.jsonl`, `webhook.jsonl`, `final-HE-1.json`,
`blocked-HE-2.json`, `blocked-HE-3.json`, `status-when-answered.json`, `answer.json`,
`hello-with-the-answer.py`, `final-HE-2.json`, `checks.json`, `result.json`, the task folders and
`cleanup.json`. Read `checks.json` and the samples yourself; `result.json` alone is not the proof.

Gotchas:
- Token counts come from opencode's own session database for the worker's folder, so they need the
  real `~/.local/share/opencode` that `bin/hw-opencode` points opencode at. A different agent that
  keeps no readable count shows `unknown`; that is correct, not a failure.
- The part 1 token budget relies on the model's provider reporting cache reads (deepseek-flash
  through opencode reports over a million per session). With a provider that reports none, the
  "cached input alone would have broken" check cannot pass; pick a budget and model that separate
  the two counts rather than weaken the check.
- A second verifier is not a failure. When the first one's `claims.json` is unusable (seen live: an
  `evidence` value listing several files), the gate would refuse it, so `hw run` starts one more
  verifier, as the coordinator's rule 30 does. A fix round (a builder with `round` above 0) is a
  failure in parts 1 and 3.
- The 0.15 minute budget stops the builder within seconds of its start. If it had already committed,
  the replacement in part 3 continues from that commit (`tests.test_run` covers that case with a
  fake builder); the journey accepts either.
- Part 3 sends the answer after the build stage on purpose: an answer during the build is already
  handled before any verifier starts, while one during verification or the evidence review is the
  case that used to be dropped. The journey fails if the task ends before the answer can be sent.
- The webhook URL carries a token in its query string. The journey fails if that token or the
  listener's port appears in any task record, status or transcript. No payload may name the
  repository's folder, the Herdworks home or the user's home folder.
- Free text that mentions a task id now goes to the coordinator, which would start a real
  coordinator session; the journey does not send one. `tests.test_run` covers that routing.
- Not covered live: opening a draft pull request from `hw run` (no remote here; `tests.test_run`
  runs the real `open_pr` against a bare local remote and the stand-in `gh`, and `draft-pr` covers
  `hw pr` live), a builder's BLOCKED question answered through `hw say --task`, an answer landing
  just as a run ends, an answer that needs no code change, fix rounds, escalation, a stalled worker
  and the manual-verification handover (all in `tests.test_run` with fake agents), and Codex token
  counts (`tokens_used` was compared read-only with four real Codex threads' own usage records: it
  equals input, cached input included, plus output; no Codex worker ran live).
