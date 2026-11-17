# A builder needs a product decision
Sub-features: ambiguous original brief, builder BLOCKED report, lead's one question, status waiting.
User entry: start with fixtures/hello/briefs/ambiguous.md.
Harness: journey.py blocked-builder --evidence ABS_PATH.
Inspect ask.md for exactly one product question with a recommendation, evidence and risk;
report.md must start BLOCKED and the branch remains at the base.
Gotchas: this is a real missing product choice, not a simulated failing CLI. No answer/resume in FH-1.
