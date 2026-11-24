# HW-11 · Direct merge command evidence for HW-7

**Call: GO for the isolated Linux direct-command criterion.** Live GitHub branch
protection and required-check enforcement remain **NOT_PROVED**. This spike
supplies evidence for HW-7 review and leaves its candidate, verdict, review
and gate unchanged.

| Criterion | Grade | Observed result and evidence |
| --- | --- | --- |
| Run the actual HW-7 command on agent-dev against an existing fixture PR | PROVED | The sender and receiver bundle digests matched. The detached checkout was clean at `610fa3acebe97e050beeba00de11e7f8f43d1903`. The fixture published PR 1 as open and ready before the separate candidate CLI process ran. See `transfer.txt`, `received-bundle.txt`, `candidate.txt`, `publication.txt`, `before/` and `merge-green.txt`. |
| Send the verified HEAD and retain the outcome | PROVED | The CLI exited 0. The publisher received one lookup and one `mergePullRequest` with `expectedHeadOid: $sha`, binding `326f05947674acb4bcd3d6ec852b1a159ba56f00` and method `SQUASH`. The fixture PR went from `OPEN` to `MERGED`. The local bare `refs/heads/main` went from `5e8ee50e6ee3d658a44d3877895e5781fbd90d32` to `9fe6e63fbb6c7eeb755f020af4b638a44fc541d8`. The new target has the original target as parent and the verified head's tree. Task events ended with `pr`, `green-merge-started`, and `green-merge` with `merged: true`. See `publisher.jsonl`, `before/refs.json`, `after/` and `assertions.json`. |
| Isolate and clean the test | PROVED | The verify-herdworks doctor identified a scratch core and a disposable home on Linux. The terminal lists were empty before and after. The scratch core stopped, its runtime had no sockets, and SSH reported removal of the temporary root. Git transport in the run was restricted to local files and the publisher was an executable fixture using `github.invalid`. See `doctor.json`, `terminals-before.json`, `terminals-after.json`, `core-cleanup.txt`, `ssh-stderr.txt` and `remote-exit.txt`. |
| Live GitHub branch protection and required checks | NOT_PROVED | The publisher supplied modeled GraphQL policy and PR responses. A live repository and identity subject to GitHub enforcement would be needed to grade real provider behavior. |

The table above records the builder's first run. Fixture task history includes
seeded build, verification and review records to exercise the candidate's gate.

## Independent run and HW-7 attachment

Paths below are relative to the Herdworks Project directory.

| Criterion | Grade | Observed result and evidence |
| --- | --- | --- |
| Independent direct command on the pinned Linux candidate | PROVED | From the clean checkout of `610fa3acebe97e050beeba00de11e7f8f43d1903`, `/tmp/hw11.QVPqY5JW/candidate/bin/hw merge-green hello HE-1` exited 0. The publisher received one synchronous merge pinned to `d15735cafa722b2cbfe41f93aebb5fa6957a0a05`. The previously open, ready PR became `MERGED`. Bare main advanced from `df4701a2b60a5acda8c4e613dda2b12f7fac642f` to `e69074c5ce1babecae92871c23d6dc5f5922c3ef`. The task appended its guarded merge start and success. The operator cleaned up the empty scratch core and disposable root. See `tasks/HW-11/verify-1/evidence/agent-dev-verifier/` and its sibling `verify_observations.py`. |
| Attach the evidence-only continuation outcome to HW-7 | PROVED | The original gate refused after the third fix. Owner message 18 authorized the linked continuation and outbox 000037 designated HW-11. HW-7's catchup now records the fixture result, verified HEAD and live GitHub limitation. Its `evidence-link` decision points to the same independent verdict, raw trace and review. Both records are under `coordinator/tasks/HW-7/`. The original refusal on the pinned candidate remains in `tasks/HW-7/events.jsonl`. |
| Live GitHub branch protection and required-check enforcement | NOT_PROVED | The independent run used the same local fixture boundary. See `tasks/HW-11/verify-1/verdict.md`. |

The first reviewer accepted the fixture trace and rejected the verdict's
coverage of the attachment. The coordinator recorded the attachment after that
review. The builder checked the new records and their references without
altering either task's existing verdict, review or gate.

Run these read-only checks from the fix worktree:

```sh
python3 ../../verify-1/evidence/verify_observations.py ../../verify-1/evidence/agent-dev-verifier
python3 docs/spikes/hw-11/check-link-back.py ../../../..
git rev-parse refs/heads/hw/HW-7
```

The first two commands exited 0. The first rechecked the raw independent
capture. The second checked the catchup, decision and original HW-7 gate
records. The ref resolved to the pinned candidate. See
`tasks/HW-11/build-2/evidence/`.

## Reproduce

With the HW-7 commit available in the local object store and the authorized
`agent-dev` alias configured, run from the findings checkout:

```sh
bash docs/spikes/hw-11/run-agent-dev.sh ../evidence/agent-dev-repeat
```

The successful run used `../evidence/agent-dev-1`. Under its disposable root,
the two proof commands were:

```sh
/tmp/hw11.vSm9Rslr/candidate/bin/hw merge-green hello HE-1
cd /tmp/hw11.vSm9Rslr/candidate
python3 -m unittest discover -s tests
```

The CLI printed `Merged verified green HEAD 326f05947674acb4bcd3d6ec852b1a159ba56f00`.
The suite exited 0 after running 278 tests, with 7 skips. The first SSH
probe was refused by the local network sandbox. The authorized runner
invocation succeeded. See `../evidence/runner-probe.txt` and
`../evidence/agent-dev-1` from the findings checkout.
