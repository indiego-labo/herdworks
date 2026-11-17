---
name: herdworks
description: Hand coding tasks to a Herdworks Project and follow them to a draft pull request. Use when the user asks to give a task to a Project or "send it to Herdworks", asks how a Herdworks task is going, or answers a question from a Project's coordinator. Relies on the `hw` command.
---

# Herdworks as your Bot

Herdworks runs a coordinator per Project (one GitHub repository). It turns a message into a
task, has one agent build it and others verify it, and ends with a draft pull request. You are
the go-between: pass the user's words in, watch for replies, and report back. You do not
build, verify or merge anything yourself.

## Find where `hw` runs

- `command -v hw` works here: run commands as written below.
- Otherwise the user's Projects live on another machine. Ask which, then prefix every command
  with `ssh HOST` (or `hc exec --on HOST -- bash -lc '...'` if they use herdr core machines).
- `hw tasks PROJECT` and `hw status` show what exists. Project names are lowercase, at most 12
  characters; `ls ~/.herdworks/projects` lists them.

## Give a Project a task

1. Note the newest reply first, so nothing that arrives during sending is missed:
   `last=$(hw read PROJECT --latest)`
2. Send the user's request with their own words. Add a done check only if the user gave one or
   agrees to yours; never add requirements they did not ask for:
   `hw say PROJECT "THE USER'S REQUEST. Done when ..."`
   Several unrelated tasks can go in separate messages. Each gets an id such as `MY-1`.
3. Start waiting in the background (in Claude Code, run it as a background command so you are
   told when it ends, and keep talking to the user meanwhile):
   `hw wait PROJECT --since "$last" --timeout 3600`
4. Tell the user it is handed over and that you will report when the Project replies.

## When `hw wait` ends

It prints each new reply as its number, then the reply. The first line of each reply is its kind:

| Kind | What to do |
| --- | --- |
| `REPLY` | Progress or an acknowledgement. Summarise it in one line for the user. |
| `QUESTION` | The coordinator needs a decision. Show the user the question and its options in plain words. Send their answer, unchanged, with `hw say PROJECT "..."`. Never answer a product question on the user's behalf. |
| `DONE` | The task finished. Report its status and the pull request address. If it says `needs manual verification`, tell the user exactly what they need to check by hand. |
| `PROBLEM` | Something needs the owner (an automation switched itself off, a limit was hit). Report it as written. |

Then run `hw wait PROJECT --since NEWEST_NUMBER --timeout 3600` again while any task is still
open (`hw tasks PROJECT` shows them). Exit code 2 means the timeout passed with no reply: check
`hw tasks PROJECT`, and wait again if work is still running.

## Checking in

- `hw tasks PROJECT`: each task, its status (`in progress`, `waiting on you`, `for review`,
  `needs manual verification`, `verified`, `stopped`) and its pull request.
- `hw read PROJECT --since N`: replies after number N.
- `hw status`: the live agents; `hc attach NAME` lets the user watch one.

## Limits

- Never merge, close or approve pull requests, push to branches, or edit files under
  `~/.herdworks`. The user reviews and merges.
- To stop a task, send the user's request to the coordinator (`hw say PROJECT "Stop MY-1"`).
- How workers build and verify is set by house rules (`hw rules`); suggest the user edits them
  with `hw rules copy NAME [--project PROJECT]` when they want work done differently.
