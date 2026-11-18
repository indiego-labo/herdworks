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

```sh
hw say myapp "The sign-up button does nothing on mobile. Done when tapping it opens the form."
hw read myapp        # the coordinator's replies: questions, progress, the pull request
hw tasks myapp       # every task and its status
hw status            # what is running right now
```

Each message becomes a task with an id like `MY-1`. You can send more while it works.
If a task needs a decision from you, `hw read` shows the question; answer with `hw say`.

## How it works

```
you ──hw say──► coordinator ──► builder      writes the change in its own git worktree
                (one per        ──► verifier     a different agent; runs it, saves proof
                 Project)       ──► evidence reviewer   checks the proof is real
                                ──► gate         a script: verified, or not
                                └──► draft pull request on GitHub ──► you merge
```

- **Project.** One per repository, with its own coordinator, task list and memory.
- **Coordinator.** An agent that never writes code. It turns your message into a task,
  starts the workers and reports back.
- **Builder, verifier, evidence reviewer.** Separate agents, so the one that checks the work
  is never the one that wrote it.
- **Gate.** A plain script that decides whether a task counts as verified. No agent can
  mark its own work as done.
- **Draft pull request.** Every task ends as a draft for you to review. Agents never merge.
  When a check needs something the machine does not have (a phone simulator, a paid
  account), the pull request says so, marked for manual verification.

Agents run in [herdr core](https://github.com/herdrdev/herdr-core) terminals, so they keep
working when you close the window. Watch one live with `hc attach NAME` (`hw status`
prints the names).

`hw help` is the short guide; `hw help TOPIC` covers models, house rules, servers and more.

## Use it from Claude

`hw setup` installs a [Claude Code skill](skills/herdworks/SKILL.md), so you can tell Claude
"give myapp this task" in any Claude Code session on the same machine. Claude sends it with
`hw say`, waits in the background with `hw wait`, relays the coordinator's questions to you and
reports the pull request when it is done. Any other agent (Codex, a ChatGPT dot) can learn
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
folder. `hw skills --project myapp` also searches the repository's `.agents/skills` and flags
a house rule that names a skill which is not installed. To give a worker a skill per task,
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
