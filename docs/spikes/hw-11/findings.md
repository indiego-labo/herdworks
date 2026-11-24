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

The HW-11 builder operated this run from a standalone SSH process, separate
from the original HW-7 run. Fixture task history includes seeded build,
verification and review records to exercise the candidate's actual gate.
Those records represent fixture inputs. Independent review of this spike
belongs to the coordinator.

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
