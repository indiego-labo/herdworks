---
name: verify-hello
description: Prove the hello CLI's greeting and optional shout flag in a disposable fixture working copy.
---
## Launch
Use Python 3.11; no dependencies, services or credentials.
## Doctor
From the fixture root run python3 --version and confirm hello.py exists.
## Drive
Run python3 hello.py Ada and check stdout is exactly Hello, Ada! and a newline.
For the shout change, run python3 hello.py --shout Ada and check HELLO, ADA! and a newline.
Run python3 -m unittest.
## Evidence
Record commands and exact stdout in the builder report. Tests supplement the CLI commands.
## Cleanup
There are no long-lived processes. Remove only temporary files created for your proof.
