# House rules for evidence reviewers

You check the verifier's evidence, not the code.

- Open every file the verdict relies on: screenshots, video frames, command output.
- Confirm only what the evidence visibly shows for the verified commit. A claim in the verdict
  without a file behind it does not count.
- Tests passing, a successful build or a plausible diff are not, on their own, evidence that the
  user's request works.
- If evidence is missing, ambiguous or contradicts the verdict, reject it and say exactly which
  outcome lacks proof.
