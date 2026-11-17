# House rules for builders and fixers

- Before editing, find how the project is run and tested: its README, scripts, and any
  `.agents/skills/verify-*` skill. Use them rather than inventing your own.
- Write or update tests for the behaviour you change when the project has tests.
- Your own proof is the same kind of evidence a reviewer would accept: run the change the
  way a user would meet it (the page, the command, the API call) and save what you saw.
- For a fix: reproduce the failure first, find the cause, then fix the cause, not the symptom.
  Rerun the original failure to show it is gone.
- Commit message: a short Conventional Commit title (`fix: ...`, `feat: ...`) that says what changed.
