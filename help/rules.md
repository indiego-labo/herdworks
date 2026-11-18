# House rules

Every worker brief includes plain Markdown house rules: `all` for every worker, then `build`
(builders and fixers), `verify` (verifiers) or `review` (evidence reviewers).

    hw rules                              which file is in effect for each rule
    hw rules --project PROJECT            the same for one Project
    hw rules copy verify                  copy it for this machine, then edit the copy
    hw rules copy build --project PROJECT copy it for one Project only

A Project's copy wins over the machine's (`~/.herdworks/rules/`), which wins over the built-in
defaults. Updates never overwrite your copies. Good things to put in a Project's rules: how to
start the app, which test command to run, how to sign in to a test account, and what evidence
you expect to see.

## Using skills

A skill is a folder with a `SKILL.md` that an agent can load. Herdworks does not install,
fetch or edit skills: install them into `~/.agents/skills` yourself, and workers find them
there. The agent folders searched are `~/.agents/skills` (opencode and Codex), `~/.claude/skills`
(opencode), `~/.config/opencode/skills` (opencode), `~/.codex/skills` (Codex) and, for a
Project, its repository's `.agents/skills` (both). `hw skills` lists every skill a worker can
see, its folder and the agents that search it, and reports machine house-rule lines that name a
skill which is not installed: that works without `--project`. `hw skills --project PROJECT`
also searches the repository's `.agents/skills` and the Project's own rules.

A rule line names a skill in one of these ways:

- it mentions skills and puts the name in backticks (`my-skill`);
- it names a folder under `skills/` (`.agents/skills/my-skill`);
- it puts a plain name after use, load or follow. A hyphenated name counts on its own ("Use
  release-notes for every release."); a single word counts when "skill" follows it ("Use the
  review skill.").

File names such as `SKILL.md` or `index.md` are not skill names. Only the rule files in effect
are searched, so a Project's copy replaces the machine's for that rule.

Give a worker a skill in one of four ways:

- **Per task.** Say it in the message: "Use the `release-notes` skill for this task." The
  coordinator carries that into the task's brief.
- **Per Project.** Put it in the Project's house rules, so every worker on that Project sees
  it: `hw rules copy all --project PROJECT`, then edit the copy.
- **Per machine.** Put it in the machine's house rules, so every worker on this machine sees
  it: `hw rules copy all`, then edit the copy.
- **Per role.** Put it in the rule for one role: `build` for builders and fixers, `verify` for
  verifiers, `review` for evidence reviewers. For example `hw rules copy build`.

A skill or house rule never overrides the task protocol: the READY line, the verdict and
review files, the rule against starting agents, and the rule against pushing all win.

The briefs in the install's `briefs/` folder are the protocol the gate reads (the READY line,
verdict.md); change house rules, not briefs.
