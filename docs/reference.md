# Reference

Everything `hw` does, in detail. Start with the [README](../README.md) if you are new.

Python 3.11 and the standard library are sufficient. Install role templates, add a
Project for a clean repository, then send it a task:

```sh
hw install
hw project add hello --github owner/hello
hw project add local --repo /absolute/hello --base main --prefix HE
hw up hello
hw say hello --file /absolute/shout.md
hw read hello --since 0
hw tasks hello
```

`HW_HOME` selects the data directory; the default is `~/.herdworks`. A Project keeps
`project.json`, `memory/`, `tasks/`, `inbox.jsonl` and `coordinator/` there.

`hw project add NAME --github owner/repo` works for any repository the signed-in `gh`
account may push to, with no allowlist and no hand-cloning. It asks GitHub for the default
branch, checks the account may push, then clones over HTTPS with `gh`'s sign-in into
`HW_HOME/repos/owner/repo`. A repository it cannot push to is refused before anything is
cloned, and a failed add leaves no Project behind. The add turns on the usual grants: push,
ready-for-review pull requests and unsandboxed sessions. `--base BRANCH` picks another base branch.
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
from the newest remote `feature/x` and its pull request opens against that branch.

### Pull requests and evidence

After the independent verifier and evidence reviewer pass the gate, the coordinator runs
`hw pr PROJECT TASK_ID`. Owners can enable publishing with
`hw project grant PROJECT --push --pull-request`. Existing Projects keep their grants, and
`--draft-pr` remains an alias for the pull-request grant. Both verified and manual-verification
pull requests open ready for review. The `--manual-verification` route requires independent
review of the available proof and lists the environment-blocked checks in the PR. The owner
decides whether to merge.

For visible changes, the verifier saves screenshots, a short video or an animated GIF in its
evidence folder. The evidence reviewer selects inspected files and records their captions,
SHA-256 hashes and any missing visual proof in `visuals.json` next to `review.md`. The PR
shows selected media inline and labels stand-ins. Commands, check results and limitations
remain in the body, including for tasks where visuals do not apply.

On GitHub.com and GitHub Enterprise Cloud, `gh` with `pr create --attach` support (v2.99.0
or newer) uploads screenshots and playable videos directly to the repository's PR. On older
clients or other hosts, Herdworks stores images and animated GIFs in the same repository under
`hw-evidence/*` tags and embeds links pinned to their media commit. Keep these tags to preserve
the images after the task branch is deleted. Use a GIF for interaction proof on this route.
Supported media are PNG, JPEG, GIF, WebP, MP4, MOV and WebM, up to 10 MB per file. Media shares
the target repository's access scope. [GitHub attachment access](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)

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
