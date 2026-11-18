# House rules

Every worker brief includes plain Markdown house rules: `all` for every worker, then `build`
(builders and fixers), `verify` (verifiers) or `review` (evidence reviewers).

    hw rules                              which file is in effect for each rule
    hw rules --project PROJECT            the same for one Project
    hw rules copy verify                  copy it for this machine, then edit the copy
    hw rules copy build --project PROJECT copy it for one Project only

A Project's copy wins over the machine's (`~/.herdworks/rules/`), which wins over the built-in
defaults. Updates never overwrite your copies. Good things to put in a Project's rules: how to
start the app, which test command to run, how to sign in to a test account, and what evidence
you expect to see.

The briefs in the install's `briefs/` folder are the protocol the gate reads (the READY line,
verdict.md); change house rules, not briefs.
