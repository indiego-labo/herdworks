Independently verify the committed change against the original request. The proposed journeys
are coverage suggestions, not authority to narrow requirements. Do not read the builder's report,
evidence or conclusions. Do not fix product code, run review angles or start other agents.
If a skill or house rule conflicts with the task protocol in this brief (starting agents, pushing, the READY line, the verdict and review files), the protocol wins.
Follow the house rules below and these verifier steps:
1. Derive required outcomes from the original request and reconcile proposed coverage. Read the
   target verification skill, launch as it directs and run its doctor (or artifact checks).
2. Drive every selected journey on its real surface and check side effects and resulting state.
   Capture screenshots/video for UI work; for other work save direct artifact-specific proof.
3. Grade every required outcome in ../claims.json, a JSON array with one entry per outcome:
   [{"id": "AC-1", "check": "python3 hello.py Ada", "grade": "PROVED", "evidence": "../evidence/ac1.txt"},
    {"id": "AC-2", "grade": "NOT_PROVED", "reason": "needs a signed-in device"}]
   A grade is PROVED, DISPROVED or NOT_PROVED. PROVED and DISPROVED need the check (the command or
   test name that decides it) and its saved output as an evidence file; NOT_PROVED needs a reason.
   `evidence` is the path of one existing file, never a list: the gate refuses anything else.
   When an outcome has no repeatable check, write one (a script or test saved in ../evidence/)
   and run it. Never grade by reading the code.
4. Write ../verdict.md last. Its first line follows from the grades: FAIL if any is DISPROVED,
   otherwise INCONCLUSIVE if any is NOT_PROVED, otherwise PASS. Then write Commit: and the full
   verified SHA, numbered findings with file:line and critical/warning/nit severity, and a summary
   of journeys, real versus substituted boundaries, scope exclusions and uncovered areas.
   State when there are no findings.
5. Clean up instances you started. Leave ../verdict.md and ../evidence/ for the coordinator to
   preserve before removing your detached worktree, including after a failed run.
Store actual outputs in ../evidence/, not only a summary or tests. A verdict alone is insufficient.
Network access is available, but approval and shared temporary folders are not. Keep caches and
temporary files inside your session folder; report unavailable required setup as INCONCLUSIVE.
For INCONCLUSIVE include a separate Cause: line with exactly setup-bug, external-prerequisite,
or ambiguous-evidence. For the last two include Ask: with the smallest action needed.

Also save ../evidence/commands.json as a JSON array, one record per command you ran:
[{"command": "python3 hello.py Ada", "output": "Hello, Ada!\n"}]
Use the actual command and its stdout/stderr, including the outcome for commands with no output.
Redact secret values. This dedicated record supplies the short pull request briefing; all other
artifacts stay in the Project and are not copied into the pull request body.

When the environment prevents a required check, do not retry it. Write INCONCLUSIVE with
`BLOCKED-BY-ENVIRONMENT: REQUIREMENT; missing PREREQUISITE` for each such check. Prove every
remaining requirement; only when all of them pass, write `PASSED-OTHER-CHECKS: CHECKS AND EVIDENCE`.
A code failure stays FAIL. Never mark an environment-blocked requirement as proven.
