Apply the evidence gate in the house rules below.
Inspect the actual files in the supplied verifier evidence folder and read its verdict and
original acceptance requirements. For UI work inspect screenshots/video and whether they visibly
show the required state. For non-UI work inspect the direct artifact-specific proof, including
exact commands and outputs; tests, compilation or a plausible diff alone are insufficient.
Confirm only when the evidence supports the required state for the verified commit and the
verdict opens with PASS, or is INCONCLUSIVE solely for explicit BLOCKED-BY-ENVIRONMENT
requirements with PASSED-OTHER-CHECKS and direct evidence for every remaining check.
For that partial verdict CONFIRMED confirms only the available proof, not the blocked requirements. Empty, ambiguous, missing or contradictory evidence is REJECTED.
Write ../review.md opening exactly CONFIRMED, REJECTED or INCONCLUSIVE. Include the commit, paths inspected,
coverage and reasons. Do not fix or generate replacement evidence, edit the verdict or product,
start agents or ask for confirmation. Your judgement must come from inspecting the saved files.

If the environment blocks your own check, use INCONCLUSIVE and one line per requirement:
`BLOCKED-BY-ENVIRONMENT: REQUIREMENT; missing PREREQUISITE`. Inspect all other checks and
only if they pass write `PASSED-OTHER-CHECKS: CHECKS AND EVIDENCE`. Never retry an environment
blocker or misclassify missing, contradictory or failed evidence as an environment limitation.
