# A lead writes only its own artifacts
Sub-features: lead-mode permissions, direct worker-file and shared temporary-root denial,
private temporary storage, factory tool escape and caller identity.
User entry: run a lead in its own run folder using bin/hw-codex lead.
Harness: journey.py lead-cannot-write --evidence ABS_PATH.
Inspect boundary-targets.json, direct-error.json and tool-result.json plus events and the worker
brief/worktree. Each direct target must record EACCES or EPERM and remain absent. Fresh owned
targets under /tmp and the inherited $TMPDIR make this fail on an unsafe launcher regardless of
checkout location. The harness removes these temporary folders after success or failure.
Gotchas: herdr state/runtime are also writable for hc; this boundary prevents accidental artifact
forgery, not a malicious lead with access to hc exec. The ephemeral boundary template is removed.
