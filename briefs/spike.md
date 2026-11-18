This task is a spike: its deliverable is an evidenced answer, not shipped behaviour. A criterion
graded DISPROVED is a finding (a no-go), not a bug, and nobody bends the work to turn it into a yes.
Builder: commit the findings and a go or no-go call, each finding with the command or test that shows it.
Verifier: this replaces the first-line rule in step 4. Open verdict.md with PASS once every criterion
is PROVED or DISPROVED with its check and evidence, or NOT_PROVED with a reason; use INCONCLUSIVE
only while a NOT_PROVED still needs a retry or a prerequisite. Add a line `Call: GO` or
`Call: NO-GO` that follows from the grades.
Evidence reviewer: confirm when every grade is backed by its evidence and the call follows from the grades.
