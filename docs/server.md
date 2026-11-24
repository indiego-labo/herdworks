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

After reading a worker's result, the coordinator runs `hw reap`. This ends the completed
sessions and removes clean builder checkouts with matching READY reports and clean verifier
checkouts with verdicts. A Project startup or pickup checks again for ended workers the
coordinator missed. `hw tidy` makes the same local check, including leftover checkouts from
stopped and closed tasks. The coordinator runs tidy on a new message. You can run it while the
coordinator is down:

```sh
hw tidy myapp
hw task close myapp MY-1
df -h "$HOME"
```

Automatic cleanup checks the recorded worker and Git registration. It keeps live sessions'
checkouts, including idle sessions and those with no attached client. It also keeps checkouts
with unfinished steps, Git locks, local changes, untracked files, or a verifier HEAD that
differs from the assigned commit. Ignored files keep a checkout in place unless the Project
owner has explicitly allowed their directory to be removed. Tidy closes a task with a merged
or closed pull request once its worker checkouts are gone.

For a Node Project, the owner can add `"generated_worktree_dirs": ["node_modules", ".next"]`
to its existing `project.json` in the Herdworks home. List only top-level directories whose
entire ignored contents can be regenerated. A listed name must be a real directory at the
root of the checkout. The repository's Git ignore rules must already cover the generated files.
Ignored state elsewhere, such as `.env.local` or local data, still keeps the checkout in place.
With no setting, all ignored state keeps the checkout in place. Reinstall dependencies and
regenerate caches as needed in a fresh continuation checkout.

The task branch and the records beside each checkout stay in place, including reports, terminal
captures, and evidence media. A fix gets a fresh worktree on the task branch. A later verifier
gets a detached checkout at the recorded build commit. A replacement of an unfinished worker
follows the existing replacement rules. Explicit stop, close and builder replacement can save
ordinary uncommitted changes as `unsaved.patch` beside the checkout. Apply it with `git apply`.
Move any ignored files you want to keep before asking Herdworks to remove that checkout.

Reclamation releases the checkout's exclusive allocation. Hard-linked package files can
occupy less exclusive space than their apparent size. Git objects, verification evidence,
package-manager caches and agent caches outside the checkout, and unrelated repositories in
temporary directories stay in place.

## Updating

Run the install command again. To install a particular branch, tag or commit:

```sh
curl -fsSL https://raw.githubusercontent.com/indiego-labo/herdworks/main/install.sh | bash -s -- TAG_OR_BRANCH
```

From a clone on your laptop, `scripts/ship-to-host.sh myserver [REF]` installs a pushed ref on
a server added with `hc machine add`.

For an existing Project on agent-dev, install a published ref containing the cleanup on that
host. Use the existing Project and its current coordinator. As the owner, add
`generated_worktree_dirs` to that Project's `project.json` if it has disposable directories.
Run `hw tidy PROJECT` on the host to sweep finished checkouts already on disk.
