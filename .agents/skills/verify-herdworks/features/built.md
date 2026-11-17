# One brief to a built commit
Sub-features: install, start, four-source worker brief, parent labels, probe, status, unattended launch.
User entry: bin/hw start --repo REPO --brief REPO/briefs/shout.md --id ID after install.
Harness: journey.py built --evidence ABS_PATH. Inspect intent.md's done check, report.md's full SHA,
catchup.md's matching SHA, status.txt, events.jsonl and direct CLI proof.
Gotchas: startup idle at turn 0 is not done; hc get has a nested status object. Status samples
are observations at check-ins, not a claim of continuous telemetry. No session keys are sent.
