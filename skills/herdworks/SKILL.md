---
name: herdworks
description: Hand coding tasks to a Herdworks Project and follow them to a draft pull request. Use when the user asks to give a task to a Project or "send it to Herdworks", asks how a Herdworks task is going, or answers a question from a Project's coordinator. Relies on the `hw` command.
---

# Herdworks as your Bot

Herdworks takes a coding task for a Project (one GitHub repository), has one agent build it and
others verify it, and ends with a draft pull request. You are the go-between: pass the user's
words in, follow the task, and report back. You do not build, verify or merge anything yourself.

## Find where `hw` runs

- `command -v hw` works here: run commands as written below.
- Otherwise the user's Projects live on another machine. Ask which, then prefix every command
  with `ssh HOST` (or `hc exec --on HOST -- bash -lc '...'` if they use herdr core machines).
- `hw tasks PROJECT` and `hw status` show what exists. Project names are lowercase, at most 12
  characters; `ls ~/.herdworks/projects` lists them.

## Give a Project a task

1. Start it with the user's own words. Add a done check only if the user gave one or agrees to
   yours; never add requirements they did not ask for:
   `hw run -p PROJECT --detach "THE USER'S REQUEST. Done when ..."`
   It prints the task id, such as `MY-1`. If they want it based on another branch, add
   `--base BRANCH`. If they gave a limit, add `--max-minutes N` or `--max-tokens N`.
2. Follow it in the background (in Claude Code, run it as a background command so you are told
   when it ends, and keep talking to the user meanwhile):
   `hw watch MY-1`
3. Tell the user it is handed over and that you will report when it ends.

## When `hw watch` ends

Its last lines are the task's status record. The exit code and `state` say how it ended:

| State | Exit | What to do |
| --- | --- | --- |
| `done` | 0 | Report the `result` line: the draft pull request address, or the verified branch and commit. If it says `needs manual verification`, tell the user exactly what to check by hand. |
| `blocked` | 2 | Show the user the `reason` and the `next` line as written. For a question, send their answer unchanged with `hw say PROJECT --task MY-1 "..."`, which resumes the task, then `hw watch MY-1` again. If that command says the answer is saved but the task was not resumed, do not send it again: run the resume command it prints. For a budget, ask before raising it with `hw run -p PROJECT --resume MY-1 --max-minutes N`. Never answer a product question on the user's behalf. |
| `failed` | 1 | Report the `reason`. `hw run -p PROJECT --resume MY-1 --detach` continues once the cause is fixed. |

## Checking in

- `hw status MY-1`: stage, elapsed time, tokens per role (input, output and reasoning; `cached=`
  is shown beside them and is not part of the count; `unknown` when the agent reports none),
  last action and branch or pull request. `hw status MY-1 --json` for the same as JSON.
- `hw status`: every open task and the live agents; a blocked task shows its reason and the
  command to continue. `hc attach NAME` lets the user watch one.
- The user adds or corrects something while a task runs: send it unchanged with
  `hw say PROJECT --task MY-1 "..."`. The task hands it to a builder before it can be done.
- `hw tasks PROJECT`: each task and its status (`in progress`, `waiting on you`, `escalated`,
  `for review`, `needs manual verification`, `verified`, `stopped`) and its pull request.

## Conversations with a coordinator

`hw say PROJECT "..."` instead hands a message to the Project's coordinator agent, which can
plan several tasks from one message and answer status questions. Note `last=$(hw read PROJECT
--latest)` first, send, then wait with `hw wait PROJECT --since "$last" --timeout 3600`. Each
reply starts with its kind: `REPLY` (progress), `QUESTION` (show it to the user and send their
answer unchanged with `hw say`), `DONE` (report the pull request) or `PROBLEM` (report it as
written). A message sent with `--task` to a closed, finished or unknown task is refused with the next step; follow it.

## Limits

- Never merge, close or approve pull requests, push to branches, or edit files under
  `~/.herdworks`. The user reviews and merges.
- To stop a task: `hw stop PROJECT MY-1`.
- How workers build and verify is set by house rules (`hw rules`); suggest the user edits them
  with `hw rules copy NAME [--project PROJECT]` when they want work done differently.
- `hw skills [--project PROJECT]` shows which skills workers can load and flags a house rule that
  names one which is not installed. The user installs skills into `~/.agents/skills`; Herdworks
  does not install them.
