# Agents and models

Each role (coordinator, builder, verifier, evidence-reviewer) runs one coding agent: opencode
or Codex. Choose per role in `~/.herdworks/config.json`; `hw config` prints what is in effect.

## opencode (default after hw setup)

    {"agents": {"builder": {"agent": "opencode", "model": "deepseek/deepseek-flash"}, ...}}

- `opencode models` lists the names you can use. Free models (`opencode/...-free`) need no
  account but run out quickly; sign in to a provider with `opencode auth login`.
- opencode runs without an operating-system sandbox, so a Project must allow it once:
  `hw project grant PROJECT --unsandboxed` (hw setup does this for the Projects it adds).

## Codex

    {"agents": {"builder": {"agent": "codex"}, ...}}

- Sign in once with `codex login`. Add `"model": "NAME"` to choose a model; check
  `~/.codex/config.toml` for the one you use today.
- On macOS, Codex workers run in the operating-system sandbox with write access to their own
  worktree only. On Linux, set `"sandbox": "off"` in the same file.

## Mixing

Any role can use either agent. A cheap model for the coordinator and a stronger one for the
builder and verifier is a common choice. A Project can override roles in its own
`~/.herdworks/projects/PROJECT/project.json` under the same `agents` key. New workers pick up
changes; running ones keep their agent.
