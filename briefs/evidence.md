Apply the evidence gate in the house rules below.
If a skill or house rule conflicts with the task protocol in this brief (starting agents, pushing, the READY line, the verdict and review files), the protocol wins.
Inspect the actual files in the supplied verifier evidence folder and read its verdict and
original acceptance requirements. For UI work inspect screenshots/video and whether they visibly
show the required state. For non-UI work inspect the direct artifact-specific proof, including
exact commands and outputs; tests, compilation or a plausible diff alone are insufficient.
Read claims.json beside the verdict: reject when it omits an outcome the original request
requires, or when a claim's evidence file does not show what its grade says.
Confirm only when the evidence supports the required state for the verified commit and the
verdict opens with PASS, or is INCONCLUSIVE solely for explicit BLOCKED-BY-ENVIRONMENT
requirements with PASSED-OTHER-CHECKS and direct evidence for every remaining check.
For that partial verdict CONFIRMED confirms only the available proof, not the blocked requirements. Empty, ambiguous, missing or contradictory evidence is REJECTED.
Write ../review.md opening exactly CONFIRMED, REJECTED or INCONCLUSIVE. Include the commit, paths inspected,
coverage and reasons. Do not fix or generate replacement evidence, edit the verdict or product,
start agents or ask for confirmation. Your judgement must come from inspecting the saved files.

For visual proof, select relevant media you inspected and found safe for the repository's readers.
Before writing review.md, save ../visuals.json with this structure:
{"media":[{"file":"result.png","caption":"Greeting after submit","source":"live","sha256":"HEX_DIGEST"}],"unavailable":[]}
Use the SHA-256 of each inspected file (for example, run shasum -a 256 FILE). List only files
directly under the verifier's evidence directory. Use source "stand-in" for fixture demonstrations
or substitutes for the target environment. If a relevant capture is missing or unsafe to publish,
state the reason in "unavailable". For interactions, compare the displayed before and after
states in the selected media with the recorded interaction. Include an animated GIF if the
Project cannot use native GitHub CLI attachments. Skip visuals.json for work with no relevant
visuals. This selection is for PR presentation and does not change any claim grade or blocker.

If the environment blocks your own check, use INCONCLUSIVE and one line per requirement:
`BLOCKED-BY-ENVIRONMENT: REQUIREMENT; missing PREREQUISITE`. Inspect all other checks and
only if they pass write `PASSED-OTHER-CHECKS: CHECKS AND EVIDENCE`. Never retry an environment
blocker or misclassify missing, contradictory or failed evidence as an environment limitation.
