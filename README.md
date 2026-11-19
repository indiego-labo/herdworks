# Herdworks

Give a coding task to a Project the way you would message a teammate. Herdworks plans it,
has one agent build it, has a different agent check it really works, and hands you a draft
pull request with the proof attached. You review and merge.

It runs on your own computer or server, with open-source agents, and needs no cloud account
beyond GitHub.

## Install

On macOS or Linux, paste this into a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/indiego-labo/herdworks/main/install.sh | bash
```

It installs everything into your home folder (no administrator password), then tells you
the next step:

```sh
hw setup
```

`hw setup` asks a few plain questions: your name for commits, a GitHub sign-in (a code you
type into the browser), which model to use (a free one is offered for a first try), and which
GitHub repository to start with. Run it again any time; it skips what is already done.

## Use it

One command in, a draft pull request out:

```sh
hw run -p myapp "The sign-up button does nothing on mobile. Done when tapping it opens the form."
```

`hw run` creates the task (an id like `MY-1`), builds it, runs your checks, has a different agent
verify it, and ends in one of three states, each with the reason and the next step:

- **done**: a draft pull request, or a verified local branch `hw/MY-1` when the Project has not
  granted pull requests.
- **blocked**: it needs you (a question, a budget, a repeated failure). The output names the
  exact command to continue.
- **failed**: something broke while driving it; `hw run -p myapp --resume MY-1` continues.

It prints each change while it works. Add `--detach` to run it in the background, and follow
or check it from anywhere:

```sh
hw status MY-1       # stage, elapsed time, tokens per role, last action, branch or pull request
hw watch MY-1        # follow it until it is done, blocked or failed
hw status            # everything that is running
```

Add `--json` to `hw status`, `hw watch` or `hw run` for scripts. Tokens are the agents' own
counts; when an agent reports none, the status says `unknown` rather than guess.

Keep a task from running away with a budget, per task or per Project:

```sh
hw run -p myapp --max-minutes 60 --max-tokens 20000000 "..."
```

When a budget is hit, `hw run` stops the task's agents and marks it blocked with the reason.
A Project can also name a `webhook` URL that receives a JSON POST when a task is done, blocked,
failed or over budget. See [docs/reference.md](docs/reference.md#one-command-runs).

Any repository your GitHub sign-in can push to can become a Project; Herdworks clones it
for you under `~/.herdworks/repos`, so there is nothing to clone by hand:

```sh
hw project add myapp --github owner/myapp
hw run -p myapp --base release/2 "Backport the sign-up fix. Done when the tests pass."
```

Tasks start from the newest version of their base branch on GitHub, and a `--base` task's
draft pull request opens against that branch.

### Or talk to a coordinator

`hw say` hands a message to the Project's coordinator, an agent that plans tasks, answers
status questions and can run several tasks from one message:

```sh
hw say myapp "Two things: fix the sign-up button, and add a dark mode toggle."
hw read myapp        # the coordinator's replies: questions, progress, the pull request
hw tasks myapp       # every task and its status
```

If a task needs a decision from you, `hw read` shows the question; answer with `hw say`.
A message that names a closed or unknown task is refused with the next step instead of being
left unanswered.

## How hw works

```
you ──hw run──► builder             writes the change in its own git worktree
                ──► checks          your test command, if the Project sets one
                ──► verifier        a different agent; runs it, saves proof
                ──► evidence reviewer   checks the proof is real
                ──► gate            a script: verified, or not
                └──► draft pull request on GitHub ──► you merge
```

- **Project.** One per repository, with its own task list and memory.
- **`hw run`.** A plain program, not an agent, moves the task from step to step. It reads what
  each agent left behind and starts the next one, so progress never depends on an agent
  remembering instructions. It saves a status record after every step.
- **Builder, verifier, evidence reviewer.** Separate agents, so the one that checks the work
  is never the one that wrote it. Each role can use its own agent and model (`hw help models`).
- **Gate.** A plain script that decides whether a task counts as verified. No agent can
  mark its own work as done.
- **Draft pull request.** Every task ends as a draft for you to review. Agents never merge.
  When a check needs something the machine does not have (a phone simulator, a paid
  account), the pull request says so, marked for manual verification.
- **Coordinator.** With `hw say`, an agent that never writes code sits in front of the same
  workers and gate, for conversations and several tasks at once.

Agents run in [herdr core](https://github.com/herdrdev/herdr-core) terminals, so they keep
working when you close the window. Watch one live with `hc attach NAME` (`hw status`
prints the names).

`hw help` is the short guide; `hw help TOPIC` covers models, house rules, servers and more.

## Use it from Claude

`hw setup` installs a [Claude Code skill](skills/herdworks/SKILL.md), so you can tell Claude
"give myapp this task" in any Claude Code session on the same machine. Claude starts it with
`hw run --detach`, follows it with `hw watch`, relays any question to you and reports the pull
request when it is done. Any other agent (Codex, a ChatGPT dot) can learn
the same steps by running `hw help agent` first.

## House rules

Every worker follows plain Markdown house rules: how to work, how to prove a change, what
counts as evidence. See them with `hw rules`. To change them, copy one and edit it:

```sh
hw rules copy verify                   # for every Project on this machine
hw rules copy build --project myapp    # for one Project only
```

A Project's copy wins over the machine's, which wins over the defaults in [rules/](rules/).
Updates never overwrite your copies.

## Skills

A skill is a folder with a `SKILL.md` that the agents can load. Install them into
`~/.agents/skills`; Herdworks does not install, fetch or edit them. `hw skills` lists the
skills a worker can see, where each one lives and which agents (opencode, Codex) search that
folder, and reports machine house-rule lines that name a skill which is not installed, without
needing `--project`. `hw skills --project myapp` additionally searches the repository's
`.agents/skills` and the Project's own rules. To give a worker a skill per task,
per Project, per machine or per role, see `hw help rules`.

## Models

Herdworks uses [opencode](https://opencode.ai) for its agents. `hw setup` offers a free model
so you can try it with no account, but free models have a small usage limit: in testing, one
small task used it up before its last check finished. For real use, sign in to a provider with
`opencode auth login` (DeepSeek costs cents per task), then run `hw setup` again and pick one.
Settings live in `~/.herdworks/config.json`.

## Run it on a server

A small always-on Linux machine keeps tasks running while your laptop sleeps. Run the same
install command there, over SSH. See [docs/server.md](docs/server.md).

## Update and uninstall

Run the install command again to update. To remove Herdworks:

```sh
rm -rf ~/.local/share/herdworks ~/.local/bin/hw
rm -rf ~/.herdworks    # also deletes your Projects' task history and memory
```

The installer also added uv, herdr core (`hc`), opencode and gh if they were missing; they
are separate tools and stay unless you remove them.

## More

- [docs/reference.md](docs/reference.md): every command, limits, memory, agents and sandboxing.
- [docs/automations.md](docs/automations.md): pick up GitHub issues or run on a schedule.
- [docs/server.md](docs/server.md): running on a Linux server.
- [.agents/skills/verify-herdworks](.agents/skills/verify-herdworks/SKILL.md): how Herdworks itself is tested.

Herdworks is early software. It runs agents with full access to the machine it is installed
on; use a machine or account you are comfortable giving them.

## License

MIT. See [LICENSE](LICENSE).
