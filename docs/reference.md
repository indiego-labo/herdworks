# Reference

Everything `hw` does, in detail. Start with the [README](../README.md) if you are new.

Python 3.11 and the standard library are sufficient. Install role templates, add a
Project for a clean repository, then give it a task, either in one command or through its
coordinator:

```sh
hw install
hw project add hello --github owner/hello
hw project add local --repo /absolute/hello --base main --prefix HE
hw run -p hello --file /absolute/shout.md      # one command; see below
hw up hello                                    # or: start the coordinator and talk to it
hw say hello --file /absolute/shout.md
hw read hello --since 0
hw tasks hello
```

## One-command runs

```sh
hw run -p hello "Add a --shout flag. Done when python3 hello.py --shout Ada prints HELLO, ADA!"
hw run -p hello --file /absolute/brief.md --base feature/x --max-minutes 60 --max-tokens 20000000
hw run -p hello --detach "..."         # in a herdr core terminal; returns at once
hw run -p hello --resume HE-2          # continue a blocked, failed or interrupted task
hw status HE-2 [--json]                # one task's status record
hw status [PROJECT] [--json]           # every open task
hw watch [HE-2] [--json]               # follow until done, blocked or failed (default: newest open task)
hw say hello --task HE-2 "the polite one"   # answer a blocked task; it resumes in the background
```

`hw run` creates the task and drives it itself, as a plain loop with no coordinator agent:
builder, the Project's `checks` command (before any verifier is spent), verifier, evidence
reviewer, gate, then a draft pull request when the Project grants `push` and `draft-pr`, else
the verified local branch. Each turn it reads the task's records and does the one next thing
they call for with the same tools the coordinator uses (`spawn`, `gate`, `reap`, `pr`), so every
existing cap applies: three fix rounds, two replacements of a stalled or dead worker per step,
one rerun of an inconclusive verifier, `max_sessions_per_task` and `max_same_reason_failures`.
`--resume` is the same loop, so it continues from whatever already exists. A worker that died or
was stopped without its artifact is replaced; a replacement builder continues from whatever the
lost builder had already committed on the task's branch. The checks command runs once per commit:
a pass before the verifier is the result the gate records.

It ends in one of three states and exits 0, 2 or 1:

| State | Meaning | Exit |
| --- | --- | --- |
| `done` | Draft pull request opened, or the commit is verified on branch `hw/TASK`. | 0 |
| `blocked` | Stopped on purpose and waiting for a person: a builder's question, a budget, a repeated gate refusal, an exhausted cap, `hw stop`, or Ctrl-C. | 2 |
| `failed` | The loop itself hit an error (a launch that could not be confirmed, a git failure). | 1 |

Blocked and failed records carry `reason` and `next_step`, the exact command to continue.
Ctrl-C stops only the loop; its workers keep running and `--resume` picks them up. `hw stop
PROJECT TASK` ends the workers, and the run then reports blocked.

### Status record

`hw run` saves `status.json` in the task folder after every step. `hw status TASK` prints it
with the live facts read fresh; `--json` gives the same record to a script:

| Field | Content |
| --- | --- |
| `task`, `project`, `driver` | `driver` is `run` or `coordinator`. |
| `state`, `stage` | `running`, `blocked`, `done` or `failed`; stage is `queued`, `build`, `verify`, `evidence`, `gate`, `pr` or `done`. |
| `status` | The word `hw tasks` shows (`in progress`, `verified`, `stopped`, ...). |
| `reason`, `next_step` | Why it stopped and what to run next; for `done`, the result. |
| `started_at`, `ended_at`, `elapsed_seconds` | Elapsed is running time: time spent blocked does not count. |
| `last_action`, `last_action_at` | The newest fact in the task's timeline: a worker started or reported, a gate answer, a stop. |
| `tokens` | Per role and `total`, as the agents report them; `"unknown"` when an agent reports none, and `partial: true` when the total leaves a session out. Never estimated. |
| `sessions` | Each worker: role, agent, model, seconds, state and its token counts (input, output, reasoning, cache read, cache write, total). |
| `budget`, `branch`, `commit`, `pr_url`, `webhook` | The limits in force, where the work is, and the last webhook delivery. |

Token counts are read from the agent's own records for the worker's folder: opencode's session
database and Codex's thread database. `total` counts every token the agent reports, cached
input included. `hw status TASK` also works for a task the coordinator drives; its record is
derived from the task's events, with elapsed time counted from the task's creation. A running
`hw run` holds a lock file in the task folder; if that process dies the lock goes with it, and
the record reads `blocked` with the resume command. Only sessions that began with the worker are
counted, so an older session from a reused folder path never adds to a task's tokens.

### Budgets

`max_minutes` and `max_tokens` are off unless set. Set them per task with `hw run --max-minutes N
--max-tokens N` (also accepted with `--resume`, to raise them), per Project in `project.json`, or
for every Project in `config.json`; the nearest one wins. `hw run` checks them every few seconds.
When one is reached it stops the task's workers, marks the task `blocked` with the reason and
sends the webhook with `"event": "budget"`. `spawn` also refuses to start a worker for any task
that is over budget, so a coordinator-driven task is capped too (its minutes count from the
task's creation). Only a running `hw run` stops workers: for a coordinator's task, or after the
`hw run` process has died, a worker already started keeps going until it ends and no further one
starts. A token budget only counts tokens an agent reports: sessions whose count is `unknown`
cannot be held to it, and the status says which those are. Time a task spends held by a machine
limit counts as running time. A blocked task keeps its place under `max_tasks_at_once` until it
finishes or you end it with `hw stop`.

### Webhook

Add `"webhook": "https://example.com/hook"` to a Project's `project.json` (or to `config.json`).
When a `hw run` task becomes `done`, `blocked` or `failed`, or hits a budget, Herdworks sends one
JSON `POST` with `event` (`done`, `blocked`, `failed` or `budget`), `at`, and these record
fields: `project`, `task`, `state`, `stage`, `status`, `reason`, `next_step`, `started_at`,
`ended_at`, `elapsed_seconds`, `last_action`, `last_action_at`, `tokens`, `budget`, `branch`,
`commit`, `pr_url`. It uses Python's standard library, waits at most ten seconds and never
retries. A delivery failure is recorded on the task (`webhook: not delivered (HTTP 500)`) and
never changes the task's outcome. The URL is treated as a secret: it is never written to the
task's records, the status or the output, and text in the payload is redacted the same way as
pull request bodies.

### Messages that name a task

`hw say PROJECT --task TASK "..."` addresses one task. For a `hw run` task the text is saved as
an answer (it goes into the next worker's brief) and a blocked task resumes in the background.
For a coordinator's task it is delivered to the coordinator as `MESSAGE N about TASK`. A message
is never recorded and then ignored:

- naming a closed task, with `--task` or in the text, is refused: the error says it is closed
  and to start a follow-up with `hw run`;
- naming an id that is not a task of the Project is refused, with `hw tasks PROJECT` as the next step;
- naming a `hw run` task in plain text is refused, with the `--task` command to use;
- `--task` on a finished `hw run` task is refused, with the follow-up command.

`--new` sends a plain message to the coordinator as written, for a new request that only
mentions an old task. `hw run` and `hw say --task` are the owner's commands: an agent session
calling them is refused. A `hw run` task accepts as an answer only a message sent with `--task`,
and such a message is never redelivered to the coordinator. The coordinator cannot start workers,
run the gate or open a pull request for a `hw run` task; those calls are refused and it reports
from `hw status TASK`.

## Projects and the coordinator

`HW_HOME` selects the data directory; the default is `~/.herdworks`. A Project keeps
`project.json`, `memory/`, `tasks/`, `inbox.jsonl` and `coordinator/` there.

`hw project add NAME --github owner/repo` works for any repository the signed-in `gh`
account may push to, with no allowlist and no hand-cloning. It asks GitHub for the default
branch, checks the account may push, then clones over HTTPS with `gh`'s sign-in into
`HW_HOME/repos/owner/repo`. A repository it cannot push to is refused before anything is
cloned, and a failed add leaves no Project behind. The add turns on the usual grants: push,
draft pull requests and unsandboxed sessions. `--base BRANCH` picks another base branch.
`--repo PATH` adds a checkout you already have and clones nothing.

Every new task fetches the Project's remote first and starts from the newest remote copy of
its base branch, so a task made after someone pushes to GitHub includes that push. A task
that names no base uses the Project's base branch. Project names
are at most 12 lowercase letters, digits, hyphens or underscores. Task prefixes are
two uppercase letters, defaulting to the first two letters in the Project name (padded with X if needed).
Tasks receive rising ids such as `HE-1` and a branch `hw/HE-1` from the Project's
configured base branch. The coordinator takes one task at a time; later tasks are queued.

`up` starts the Project's one coordinator, `hw-hello-coord`, with no parent. It refuses
a second live coordinator. `say` also brings a missing coordinator up. Messages are
recorded unchanged with rising numbers before delivery; `say hello --number 1` retries
that exact message after a delivery error. Repeated numbers reuse their task and receive
a repeat acknowledgement. A blocked coordinator is reported without forced input.
`say hello --base feature/x "..."` records `feature/x` with that message: the task starts
from the newest remote `feature/x` and its draft pull request opens against that branch.

Replies are numbered `.md` files under `coordinator/outbox/`, beginning `REPLY`, `QUESTION`
or `DONE`. `read --since N` returns only reply numbers greater than N. The coordinator
keeps task notes in `coordinator/tasks/HE-1/`. A QUESTION leaves the task `waiting on you`;
answer with `say hello "your choice"`. If the coordinator is lost, use `up hello`; it
picks up artifacts and live workers instead of repeating completed work.

The worker tools take a Project and task id:

```sh
hw task new hello --brief /absolute/brief.md
hw spawn hello HE-1 build
hw probe hello HE-1
hw gate hello HE-1
hw reap hello HE-1
hw stop hello HE-1
```

The coordinator normally creates tasks with `task new hello --message NUMBER`, which
is idempotent. It starts the builder, a fresh detached verifier and an evidence reviewer.
Only `gate` confirms VERIFIED for the current committed branch head, a matching PASS and
CONFIRMED evidence review. Tasks derive their status from current artifacts on every read.
There are 12 worker sessions per task, three fix rounds and two replacements per step.
`stop` ends only that task's workers; the Project coordinator stays available.

The verifier grades each acceptance criterion in `claims.json` beside its verdict: an `id`, a
`check` (command or test name), a `grade` of `PROVED`, `DISPROVED` or `NOT_PROVED`, and an
`evidence` path. The gate refuses a verdict whose first line does not follow from those grades,
a `PROVED` or `DISPROVED` claim without a check and an existing evidence file, and a
`NOT_PROVED` claim without a `reason`. A fix round needs the gate's refusal of the current
commit, so run `gate` before `spawn ... fix`.

Settings that change the gate:

- `checks` in a Project's `project.json`, or in `config.json` for every Project: a shell command
  such as `"npm ci && npm test"`. `hw gate` runs it in a fresh checkout of the built commit, so
  include any install step, and refuses unless it exits 0, whatever the verdict says. The gate
  event records the command, its exit code and the end of its output, and a failure goes into
  the next fix brief. The command runs with `hw`'s own permissions, outside the worker sandbox.
- `hw task new PROJECT --kind spike` (the coordinator adds it when you ask for an answer or a
  go/no-go): the gate passes once every claim is graded and evidenced, so `DISPROVED` is an
  accepted finding.
- `max_same_reason_failures` in `config.json` or `project.json`: how many commits the gate may
  refuse for the same reasons before the task becomes `escalated`. An escalated task starts no
  worker until you answer the coordinator's question; `hw stop` ends it instead.

An evidence reviewer starts only after the verifier's `verdict.md` is written and its verifier
session has finished; `spawn ... evidence` otherwise refuses and says to wait. If the newest
review began before the verdict it inspects, `spawn ... evidence` starts a fresh review, keeps
the old one and counts the new session against the task budget. One command replaces a review
that the gate refuses.

For fixture proof, `task new --role build /absolute/program` substitutes a worker program.
Roles are build, verify and evidence. Programs receive the brief path as their sole argument
and run in a macOS operating-system sandbox with private temporary storage and no network
or core access. Builders can write their shared Git directory. Other Project records and
Herdworks source remain protected. A verifier or evidence override can never satisfy the gate.
`install` refuses templates it did not write, including edited templates.

Use the project [verify-herdworks skill](../.agents/skills/verify-herdworks/SKILL.md) for live proof.
It requires a scratch core and Herdworks home. Run unit checks with
`hc exec -- python3 -m unittest discover -s tests` from a sandboxed caller.

`hw skills [--project PROJECT]` lists the skills a worker can load: `~/.agents/skills` (opencode
and Codex), `~/.claude/skills` and `~/.config/opencode/skills` (opencode), `~/.codex/skills`
(Codex) and, with a Project, its repository's `.agents/skills` (both). It names each skill's
folder, the agents that search it, and any machine or Project house-rule line that names a skill
which is not installed. Herdworks never installs or fetches skills; `hw help rules` explains how
to give one to a task, a Project, the machine or a role.

Project memory and machine limits are stored outside the repository in Herdworks home.
`hw config` prints effective limits; edit `config.json` as the owner to change them.
The defaults are two active tasks, four live workers, six worker worktrees, 5 GiB free disk,
and twelve sessions over a task's lifetime. A Project may lower `max_tasks_at_once` in its
`project.json`. A held task remains queued and `tasks PROJECT` names the limiting setting.

Use `hw memory read PROJECT` and `hw memory add PROJECT --task TASK_ID --title TITLE
--text TEXT`. Memory entries are at most 16 KiB. Builders may also write small Markdown files
with a `Task: TASK_ID` line in the Project's memory folder; the API indexes them on its next read or start. Each task captures memory before its workers start; its verifier and evidence reviewer receive
only that saved snapshot, so later writes and edits cannot enter their packets. Store reusable
commands, quirks and user decisions, never result claims.

`config.json` may contain `agents`, keyed by `coordinator`, `builder`, `verifier`, and
`evidence-reviewer`, each with `agent` (`codex` or `opencode`) and `model`. Project `agents`
overrides individual role fields. Codex is the default. For example, an opencode role uses
`{"agent":"opencode","model":"deepseek/deepseek-flash"}`. Before using opencode, the owner
must run `hw project grant PROJECT --unsandboxed`. Its launch records and task output
identify unsandboxed sessions. The launcher uses `opencode --standalone --auto`, the user's
provider configuration and sign-in, and a private model config; it never copies sign-in files.
