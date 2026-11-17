# Running Herdworks on a Linux server

A laptop stops its agents when it sleeps. A small always-on Linux machine (a home server,
a cloud VM, a spare mini PC) keeps tasks running overnight. Ubuntu 22.04 or newer works;
4 CPUs, 8 GB of memory and 20 GB of free disk are a comfortable start.

## Install

SSH into the server as the user the agents should run as, then run the same command as on a
laptop:

```sh
curl -fsSL https://raw.githubusercontent.com/indiego-labo/herdworks/main/install.sh | bash
hw setup
```

`hw setup` signs in to GitHub with a code you type into any browser, so the server needs
no SSH keys for GitHub.

## Keep agents running after you log out

Some Linux systems stop a user's programs when that user logs out. `hw setup` tells you if
this one does. If so, run once:

```sh
sudo loginctl enable-linger "$USER"
```

## Talk to it from your laptop

Two ways, both through SSH:

- Log in and use `hw` there: `ssh server`, then `hw say myapp "..."`.
- Add the server to herdr core on your laptop, then follow its agents from there:

  ```sh
  hc machine add myserver --name myserver   # once; uses your SSH config
  hc ls                                     # lists the server's agents too
  hc attach myserver/NAME                   # watch one live
  hc exec --on myserver -- bash -lc 'hw read myapp'   # run hw there
  ```

## Machine settings

`~/.herdworks/config.json` holds the machine's limits and agent choices. `hw config` prints
the values in effect. The defaults allow two tasks at once, four live workers, six worker
worktrees and require 5 GB of free disk. See [reference.md](reference.md) for every setting.

## Disk space

Worktrees are removed as tasks go, so they do not pile up:

- A fix round or a replacement removes the previous builder's worktree.
- `reap` removes a verifier's worktree once its verdict is written.
- `stop` removes all of a task's worktrees.
- `tidy` closes tasks whose pull request was merged or closed. The coordinator runs it at the
  start of every message; you can run it too:

```sh
hw tidy myapp
hw task close myapp MY-1
df -h "$HOME"
```

Uncommitted files in a removed worktree are kept as `unsaved.patch` in the worker's folder;
apply one with `git apply`. Branches, memory, messages, briefs, reports and evidence are
always kept. Evidence folders and opencode's own caches can still grow; check them now and
then.

## Updating

Run the install command again. To install a particular branch, tag or commit:

```sh
curl -fsSL https://raw.githubusercontent.com/indiego-labo/herdworks/main/install.sh | bash -s -- TAG_OR_BRANCH
```

From a clone on your laptop, `scripts/ship-to-host.sh myserver [REF]` installs a pushed ref on
a server added with `hc machine add`.
