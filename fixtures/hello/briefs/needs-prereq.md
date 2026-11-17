Add --shout exactly as in briefs/shout.md and prove both CLI outputs and unittest.
Independent verification additionally requires the external command hello-prereq at
{{PREREQ}} to exit zero and print hello-prereq ready. It is an external prerequisite,
not something the builder should implement or install. A verifier must check it; if it
is missing, report INCONCLUSIVE with Cause: external-prerequisite and Ask: install hello-prereq.
After it becomes available, verify the same built commit again. Start no other agents.
