import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from unittest.mock import patch
from herdworks import drive, monitor, tokens
from herdworks.cli import follow, main
from herdworks.pickup import close, stop
from herdworks.projects import grant_project, read_project
from herdworks.runs import append_event, events, git
from herdworks.spawn import spawn
from herdworks.talk import inbox
from tests.support import RunCase, write_claims

FAKE_GH = Path(__file__).resolve().parents[1] / "fixtures/hello/planted/fake-gh.sh"
PULL_REQUEST = "https://github.invalid/fixture/hello/pull/1"  # what the stand-in gh answers


class Hook:
    """A local listener that records each webhook POST it receives."""
    def __init__(self, status=200):
        received = self.received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                received.append(dict(path=self.path, type=self.headers["Content-Type"], body=json.loads(body)))
                self.send_response(status)
                self.end_headers()

            def log_message(self, *args):
                pass
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook?token=SECRET-TOKEN"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RunScenario(RunCase):
    """`hw run` against fake agents: launching a session does that role's work at once, as scripted."""
    def setUp(self):
        super().setUp()
        (self.home / "config.json").write_text('{"max_worktrees": 20}')
        self.live, self.idle, self.killed, self.launched, self.detached = set(), set(), [], [], []
        self.script = {"build": [], "verify": [], "evidence": []}
        for target, effect in (("launch", self.launch), ("get", self.get), ("call", self.call),
                               ("sessions", lambda: [dict(address=name) for name in sorted(self.live | self.idle)]),
                               ("require_owner", lambda: None)):
            patcher = patch(f"herdworks.hc.{target}", side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)

    def launch(self, **kwargs):
        role, cwd = kwargs["role"], kwargs["cwd"]
        self.launched.append(kwargs)
        act = self.script[role].pop(0) if self.script[role] else "ok"
        if act == "commit-hang":
            # Commits, then never reports: what a builder killed between its commit and its report leaves.
            (cwd / "hello.py").write_text("print('half done')\n")
            git(cwd, "commit", "-am", "wip: half done")
        if act in ("hang", "commit-hang"):
            self.live.add(kwargs["name"])
        else:
            # Like a real agent, it stays in its terminal, idle, after leaving its artifact.
            getattr(self, role)(cwd, act)
            self.idle.add(kwargs["name"])
        return dict(address=kwargs["name"], name=kwargs["name"], first_message={"sent": True})

    def stamp(self, file):
        now = time.time()
        os.utime(file, (now, now))

    def build(self, wt, act):
        report = wt.parent / "report.md"
        if act == "question":
            report.write_text("BLOCKED\nShould the greeting be loud or polite?\n")
        elif act == "noop":
            report.write_text(f"READY {git(wt, 'rev-parse', 'HEAD')}\n")
        else:
            (wt / "hello.py").write_text(f"print('{wt.parent.name}')\n")
            if act == "fixed":
                (wt / "fixed.txt").write_text("fixed\n")
            git(wt, "add", ".")
            git(wt, "commit", "-m", f"feat: {wt.parent.name}")
            report.write_text(f"READY {git(wt, 'rev-parse', 'HEAD')}\n")
        self.stamp(report)

    def verify(self, wt, act):
        folder = wt.parent
        commit = git(wt, "rev-parse", "HEAD")
        (folder / "evidence").mkdir(exist_ok=True)
        (folder / "evidence/commands.json").write_text(json.dumps([dict(command="python3 hello.py", output="ok\n")]))
        if act == "environment":
            write_claims(folder, "PROVED", "NOT_PROVED")
            text = ("INCONCLUSIVE\nBLOCKED-BY-ENVIRONMENT: the device greeting; missing simulator\n"
                    "PASSED-OTHER-CHECKS: cli and unittest, evidence/ac1.txt\n")
        elif act == "inconclusive":
            write_claims(folder, "NOT_PROVED")
            text = "INCONCLUSIVE\nCause: ambiguous-evidence\nAsk: run it again with a clean cache\n"
        elif act == "prerequisite":
            write_claims(folder, "NOT_PROVED")
            text = "INCONCLUSIVE\nCause: external-prerequisite\nAsk: sign in to the simulator\n"
        else:
            # "spike-no": the answer to the question is an evidenced no, which a spike reports as PASS.
            write_claims(folder, "DISPROVED" if act in ("fail", "spike-no") else "PROVED")
            text = f"{'FAIL' if act == 'fail' else 'PASS'}\nFinding: wrong output\n"
        (folder / "verdict.md").write_text(text + f"Commit: {commit}\n")
        self.stamp(folder / "verdict.md")

    def evidence(self, work, act):
        (work.parent / "review.md").write_text("CONFIRMED\n")
        self.stamp(work.parent / "review.md")

    def get(self, name):
        if name in self.live | self.idle:
            return dict(state="live", status="working" if name in self.live else "idle", address=name, name=name,
                        labels=dict(hw=self.labels.get(name, "")))
        return dict(state="finished", address=name, name=name)

    @property
    def labels(self):
        return {launch["name"]: launch["identity"] for launch in self.launched}

    def call(self, *args):
        if args[0] == "kill":
            self.live.discard(args[1])
            self.idle.discard(args[1])
            self.killed.append(args[1])
        if args[0] == "run":
            # `hw run --detach`: stand in for the new process taking the task over.
            self.detached.append(list(map(str, args)))
            monitor.write(args[args.index("--cwd") + 1], state="running", pid=os.getpid() + 1)
        return dict(text="last screen")

    def run_task(self, text="Make hello print its build. Done when python3 hello.py prints it.", **options):
        path = drive.create(self.project, text, **options)
        return path, drive.drive(path, interval=0, sleep=lambda seconds: time.sleep(0.01))

    def hw(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def set_project(self, **settings):
        data = dict(read_project(self.project), **settings)
        (self.project / "project.json").write_text(json.dumps(data))

    def grant_pull_requests(self, gh=FAKE_GH):
        """Push and draft-pr grants against a bare local remote and a stand-in gh, as tests.test_pr does:
        the real `open_pr` runs, and nothing reaches the network or GitHub."""
        self.remote = self.root / "remote.git"
        git(self.root, "init", "--bare", self.remote)
        git(self.repo, "remote", "add", "origin", self.remote)
        git(self.repo, "push", "origin", "main")
        grant_project(self.project, True, True, gh=str(gh))

    def gh_calls(self):
        log = self.root / "fake-gh.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def coordinator(self):
        return dict(name="hw-unit-coord", address="t1", state="live", status=dict(state="idle"),
                    cwd=str(self.project / "coordinator"), labels=dict(hw="project:unit"))

    def finish_worker(self, path, folder, act="ok"):
        """Let a worker that was left hanging write its artifact and end its turn."""
        role = folder.split("-")[0]
        getattr(self, role)(path / folder / ("work" if role == "evidence" else "wt"), act)
        name = f"hw-unit-{path.name.lower()}-{folder}"
        self.live.discard(name)
        self.idle.add(name)


class OneCommandTests(RunScenario):
    def test_run_reaches_a_verified_branch_without_a_coordinator_or_a_nudge(self):
        path, final = self.run_task()
        self.assertEqual((final["state"], final["stage"], final["status"]), ("done", "done", "verified"))
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "evidence"])
        self.assertTrue(all(launch["parent"] is None for launch in self.launched))
        self.assertEqual(final["commit"], git(self.repo, "rev-parse", "refs/heads/hw/HE-2"))
        self.assertIn("verified: commit " + final["commit"], final["reason"])
        self.assertIn("has not granted push, draft-pr", final["reason"])
        self.assertIsNone(final["pr_url"])
        self.assertEqual(inbox(self.project), [])
        self.assertEqual((self.live | self.idle, len(self.killed)), (set(), 3))
        self.assertEqual([e["passed"] for e in events(path) if e["event"] == "gate"], [True])
        self.assertEqual(final["last_action"].split(":")[0], "done")
        self.assertEqual(json.loads((path / "status.json").read_text())["state"], "done")

    def test_cli_run_prints_progress_and_exits_zero_and_status_json_matches(self):
        code, out, err = self.hw("run", "-p", "unit", "Make hello print its build.")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("HE-2 on branch hw/HE-2", out)
        self.assertIn("HE-2 done stage=done", out)
        self.assertIn("result: verified: commit", out)
        code, out, _ = self.hw("status", "HE-2", "--json")
        current = json.loads(out)
        self.assertEqual((code, current["task"], current["state"], current["driver"]), (0, "HE-2", "done", "run"))
        self.assertEqual([s["role"] for s in current["sessions"]], ["build", "verify", "evidence"])
        code, out, _ = self.hw("status", "HE-2")
        self.assertIn("HE-2 done stage=done elapsed=", out)
        self.assertIn("tokens=unknown", out)

    def test_failed_verdict_gets_a_fix_round_then_passes(self):
        self.script["verify"] = ["fail", "ok"]
        path, final = self.run_task()
        self.assertEqual(final["state"], "done")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "build", "verify", "evidence"])
        self.assertIn("Finding: wrong output", (path / "build-2/brief.md").read_text())

    def test_failing_checks_stop_before_a_verifier_and_repeat_refusals_escalate(self):
        self.set_project(checks="exit 3")
        path, final = self.run_task()
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "build"])
        self.assertEqual(final["state"], "blocked")
        self.assertIn("refused 2 commits for the same reasons", final["reason"])
        self.assertIn("checks command exited 3", final["reason"])
        self.assertIn('hw say unit --task HE-2 "YOUR DECISION"', final["next_step"])

    def test_builder_question_blocks_and_the_answer_resumes_to_done(self):
        self.script["build"] = ["question", "ok"]
        path, final = self.run_task()
        self.assertEqual((final["state"], final["stage"]), ("blocked", "build"))
        self.assertIn("Should the greeting be loud or polite?", final["reason"])
        with patch("herdworks.drive.detach") as detach:
            code, out, _ = self.hw("say", "unit", "--task", "HE-2", "Polite.")
        self.assertEqual(code, 0)
        self.assertIn("delivered 1 to HE-2 and resumed it", out)
        detach.assert_called_once_with(path)
        final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(final["state"], "done")
        self.assertIn("Polite.", (path / "build-2/brief.md").read_text())

    def test_escalation_blocks_then_the_answer_continues_and_checks_never_run_twice_on_a_commit(self):
        counter = self.root / "checks-ran"
        self.set_project(checks=f"echo x >> {counter}; test -f fixed.txt")
        path, final = self.run_task()
        self.assertEqual(final["state"], "blocked")
        self.assertIn("refused 2 commits for the same reasons", final["reason"])
        self.script["build"] = ["fixed"]
        with patch("herdworks.drive.detach"):
            self.assertEqual(self.hw("say", "unit", "--task", "HE-2", "Add fixed.txt; that is what the check wants.")[0], 0)
        final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(final["state"], "done")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "build", "build", "verify", "evidence"])
        self.assertIn("that is what the check wants", (path / "build-3/brief.md").read_text())
        # Two failing commits, one refusal re-read after the answer, one passing commit checked once before its verifier.
        self.assertEqual(len(counter.read_text().splitlines()), 4)
        self.assertEqual([e["passed"] for e in events(path) if e["event"] == "gate"], [False, False, False, True])

    def test_a_held_fix_round_waits_without_running_the_gate_again(self):
        self.script["verify"] = ["fail", "ok"]
        held = []

        def sometimes_full(path, role="build", replaces=None):
            if role == "fix" and len(held) < 3:
                held.append(role)
                raise ValueError("queued: max_worker_sessions")
            return spawn(path, role, replaces=replaces)
        with patch("herdworks.drive.spawn", side_effect=sometimes_full):
            path, final = self.run_task()
        self.assertEqual((final["state"], len(held)), ("done", 3))
        self.assertEqual([e["passed"] for e in events(path) if e["event"] == "gate"], [False, True])
        waits = [e["action"] for e in events(path) if e["event"] == "run" and "held by" in e["action"]]
        self.assertEqual(waits, ["waiting for a free place: held by max_worker_sessions"])

    def test_a_stalled_worker_is_replaced_and_the_task_finishes(self):
        self.script["build"] = ["hang", "ok"]
        path = drive.create(self.project, "Request")
        stalled = [dict(name="hw-unit-he-2-build-1", stalled=True)]
        with patch("herdworks.drive.probe", side_effect=[stalled] + [[]] * 20):
            final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(final["state"], "done")
        self.assertEqual(self.killed[0], "hw-unit-he-2-build-1")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "build", "verify", "evidence"])
        self.assertTrue((path / "build-1/stalled-1.txt").is_file())

    def test_a_worker_still_in_its_turn_is_given_time_before_it_is_ended(self):
        path = drive.create(self.project, "Request")
        drive.advance(path)
        self.live, self.idle = self.idle, set()  # it wrote its report and is still typing
        step = drive.advance(path)
        self.assertEqual((step.wait, step.stage, self.killed), (True, "build", []))
        step = drive.advance(path, now=time.time() + drive.SETTLE + 1)
        self.assertEqual((step.stage, self.killed), ("verify", ["hw-unit-he-2-build-1"]))

    def test_environment_blocked_requirement_is_handed_over_not_verified(self):
        self.script["verify"] = ["environment"]
        path, final = self.run_task()
        self.assertEqual((final["state"], final["stage"], final["status"]), ("blocked", "pr", "in progress"))
        self.assertIn("needs manual verification of: the device greeting; missing simulator", final["reason"])
        self.assertIn("hw pr unit HE-2 --manual-verification", final["next_step"])
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "evidence"])
        self.grant_pull_requests()
        final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual((final["state"], final["status"], final["pr_url"]), ("done", "needs manual verification", PULL_REQUEST))
        self.assertIn(f"needs manual verification; draft pull request: {PULL_REQUEST}", final["reason"])
        (call,) = self.gh_calls()
        title = call["args"][call["args"].index("--title") + 1]
        self.assertTrue(title.startswith("[Needs manual verification] "), title)
        self.assertEqual(call["args"][-2:], ["--label", "needs-manual-verification"])
        self.assertIn("the device greeting; missing simulator", call["body"])
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/hw/HE-2"), final["commit"])

    def test_inconclusive_verdict_gets_one_more_verifier_then_asks(self):
        self.script["verify"] = ["inconclusive", "ok"]
        _, final = self.run_task()
        self.assertEqual(final["state"], "done")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "verify", "evidence"])
        self.launched.clear()
        self.script["verify"] = ["inconclusive", "inconclusive"]
        path, final = self.run_task("Second request")
        self.assertEqual((final["state"], final["stage"]), ("blocked", "verify"))
        self.assertIn("INCONCLUSIVE", final["reason"])
        self.assertIn("Ask: run it again with a clean cache", final["reason"])
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "verify"])

    def test_a_spike_with_a_disproved_finding_is_done_and_never_gets_a_fix_round(self):
        self.script["verify"] = ["spike-no"]
        _, final = self.run_task(kind="spike")
        self.assertEqual(final["state"], "done")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "evidence"])
        self.launched.clear()
        self.script["verify"] = ["fail", "fail"]
        _, final = self.run_task("Second question", kind="spike")
        self.assertEqual(final["state"], "blocked")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "verify"])

    def test_fix_builder_without_a_new_commit_blocks_instead_of_failing(self):
        self.script["verify"] = ["fail"]
        self.script["build"] = ["ok", "noop"]
        _, final = self.run_task()
        self.assertEqual((final["state"], final["stage"]), ("blocked", "build"))
        self.assertIn("reported READY without a new commit", final["reason"])
        self.assertIn("start a fresh task with: hw run -p unit", final["next_step"])

    def test_a_question_in_a_fix_round_keeps_the_findings_after_the_answer(self):
        self.script["verify"] = ["fail", "ok"]
        self.script["build"] = ["ok", "question", "ok"]
        path, final = self.run_task()
        self.assertEqual(final["state"], "blocked")
        with patch("herdworks.drive.detach"):
            self.assertEqual(self.hw("say", "unit", "--task", "HE-2", "Polite.")[0], 0)
        final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(final["state"], "done")
        brief = (path / "build-3/brief.md").read_text()
        for content in ("Finding: wrong output", "Fix round: 1 of 3", "Polite."):
            self.assertIn(content, brief)
        self.assertEqual(len([e for e in events(path) if e["event"] == "rewind"]), 1)

    def test_hw_stop_during_a_run_ends_it_blocked(self):
        self.script["build"] = ["hang"]
        path = drive.create(self.project, "Request")
        final = drive.drive(path, interval=0, sleep=lambda seconds: stop(path))
        self.assertEqual((final["state"], final["status"]), ("blocked", "stopped"))
        self.assertIn("stopped", final["reason"])
        self.assertIn("hw run -p unit --resume HE-2", final["next_step"])
        self.assertEqual(self.killed, ["hw-unit-he-2-build-1"])

    def test_detach_starts_the_same_command_in_a_terminal_that_stop_will_not_end(self):
        path = drive.create(self.project, "Request")
        code, out, _ = self.hw("run", "-p", "unit", "--resume", "HE-2", "--detach")
        self.assertEqual(code, 0)
        self.assertIn("Follow it with: hw watch HE-2", out)
        (started,) = self.detached
        self.assertEqual(started[started.index("--") + 1:][0:2], ["env", f"HW_HOME={self.home}"])
        self.assertEqual(started[-5:], ["run", "-p", "unit", "--resume", "HE-2"])
        self.assertIn("hwrun=unit:HE-2", started)
        self.assertNotIn("hw=unit:HE-2", started)
        self.assertIn("--no-parent", started)

    def test_dead_worker_is_replaced_and_a_third_death_blocks(self):
        self.script["build"] = ["hang", "hang", "hang"]
        path = drive.create(self.project, "Request")

        def die(seconds):
            self.live.clear()
        final = drive.drive(path, interval=0, sleep=die)
        self.assertEqual(final["state"], "blocked")
        self.assertEqual(len(self.launched), 3)
        self.assertIn("two replacements exhausted", final["reason"])
        self.assertIn("hw run -p unit --resume HE-2", final["next_step"])

    def test_driver_error_is_failed_with_the_error_and_the_resume_command(self):
        with patch("herdworks.drive.advance", side_effect=RuntimeError("launch outcome uncertain")):
            _, final = self.run_task()
        self.assertEqual(final["state"], "failed")
        self.assertIn("launch outcome uncertain", final["reason"])
        self.assertIn("hw run -p unit --resume HE-2", final["next_step"])

    def test_interrupt_leaves_workers_running_and_names_the_resume_command(self):
        self.script["build"] = ["hang"]
        path = drive.create(self.project, "Request")

        def interrupt(seconds):
            raise KeyboardInterrupt
        final = drive.drive(path, interval=0, sleep=interrupt)
        self.assertEqual(final["state"], "blocked")
        self.assertIn("interrupted", final["reason"])
        self.assertIn("hw run -p unit --resume HE-2", final["next_step"])
        self.assertEqual((self.killed, self.live), ([], {"hw-unit-he-2-build-1"}))

    def test_bad_budget_or_empty_request_creates_no_task(self):
        for args in (["run", "-p", "unit", "--max-minutes", "0", "Request"], ["run", "-p", "unit", "--max-tokens", "-1", "Request"],
                     ["run", "-p", "unit", "  "], ["run", "-p", "unit", "--resume", "HE-7"]):
            with self.subTest(args=args):
                code, _, err = self.hw(*args)
                self.assertEqual(code, 1)
                self.assertRegex(err, "positive number|say what you want|no task HE-7")
        self.assertFalse((self.project / "tasks/HE-2").exists())
        self.assertEqual(self.launched, [])

    def test_a_second_driver_and_a_coordinator_task_are_refused(self):
        with self.assertRaisesRegex(ValueError, "coordinator's task"):
            drive.drive(self.path)
        path = drive.create(self.project, "Request")
        with (path / ".driver.lock").open("a") as held:
            import fcntl
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaisesRegex(ValueError, "already being driven.*hw watch HE-2"):
                drive.drive(path)

    def test_coordinator_cannot_start_workers_for_a_run_task(self):
        path = drive.create(self.project, "Request")
        caller = dict(address="t1", state="live", cwd=str(self.project / "coordinator"),
                      labels=dict(hw="project:unit", role="coordinator"))
        with patch.dict(os.environ, HW_CALLER_TERMINAL="t1"), patch("herdworks.hc.get", return_value=caller):
            for args in (["spawn", "unit", "HE-2", "build"], ["gate", "unit", "HE-2"], ["reap", "unit", "HE-2"],
                         ["pr", "unit", "HE-2"]):
                with self.subTest(args=args):
                    code, _, err = self.hw(*args)
                    self.assertEqual(code, 1)
                    self.assertIn("driven by hw run", err)
            self.assertEqual(self.hw("status", "HE-2")[0], 0)
        self.assertEqual(events(path), [])

    def test_agents_cannot_start_a_run_or_answer_one_however_the_command_is_spelled(self):
        self.script["build"] = ["question"]
        path, _ = self.run_task()
        refuse = ValueError("operation must be performed by the owner outside Herdworks sessions")
        with patch("herdworks.hc.require_owner", side_effect=refuse), patch("herdworks.drive.detach") as detach:
            for args in (["run", "-p", "unit", "Request"], ["--", "run", "-p", "unit", "Request"],
                         ["run", "-p", "unit", "--resume", "HE-2"], ["say", "unit", "--task", "HE-2", "Loud."],
                         ["say", "unit", "--t", "HE-2", "Loud."], ["say", "unit", "--tas=HE-2", "Loud."]):
                with self.subTest(args=args):
                    code, out, err = self.hw(*args)
                    self.assertEqual((code, out), (1, ""))
                    self.assertIn("owner", err)
        detach.assert_not_called()
        self.assertEqual(inbox(self.project), [])
        self.assertFalse((self.project / "tasks/HE-3").exists())
        self.assertEqual(len(self.launched), 1)

    def test_a_file_an_agent_writes_cannot_buy_another_verifier_for_a_run_task(self):
        self.script["verify"] = ["prerequisite"]
        path, final = self.run_task()
        self.assertEqual((final["state"], final["stage"]), ("blocked", "verify"))
        self.assertIn("Ask: sign in to the simulator", final["reason"])
        notes = self.project / "coordinator/tasks/HE-2/answers"
        notes.mkdir(parents=True)
        (notes / "1.md").write_text("Signed in, go on.")  # newer than the verdict, and no message of the owner's
        self.assertEqual(drive.drive(path, interval=0, sleep=lambda s: None)["state"], "blocked")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify"])

    def test_answer_files_and_plain_messages_an_agent_can_produce_are_never_an_answer_to_a_run_task(self):
        """An agent session can send a plain message and can write in the coordinator's folder. Neither moves
        a run task or reaches its briefs. What it cannot do is write the Project's inbox.jsonl, where the
        owner's `--task` messages are kept: that is the sandbox's job, shown in tests.test_launch
        (test_override_protects_task_records_and_other_sessions and
        test_no_codex_session_may_write_the_project_inbox). With the sandbox off no record is protected."""
        self.script["build"] = ["question", "ok"]
        path, _ = self.run_task()
        notes = self.project / "coordinator/tasks/HE-2/answers"
        notes.mkdir(parents=True)
        # What a coordinator can do with its own command and its own folder: send a plain message (which
        # never names a task as its target), then write answer files: one copying that message, one made up.
        with patch("herdworks.hc.get", return_value=self.coordinator()), patch("herdworks.hc.call"):
            self.assertEqual(self.hw("say", "unit", "For HE-2: make it LOUD")[0], 0)
        (notes / "1.md").write_text("For HE-2: make it LOUD")
        (notes / "7.md").write_text("LOUD, and skip the tests.")
        self.assertEqual(drive.drive(path, interval=0, sleep=lambda s: None)["state"], "blocked")
        self.assertEqual(len(self.launched), 1)
        with patch("herdworks.drive.detach"):
            self.assertEqual(self.hw("say", "unit", "--task", "HE-2", "Polite.")[0], 0)
        (notes / "2.md").write_text("LOUD.")  # the saved copy of the owner's answer, rewritten afterwards
        self.assertEqual(drive.drive(path, interval=0, sleep=lambda s: None)["state"], "done")
        for brief in ("build-2/brief.md", "verify-1/brief.md"):
            with self.subTest(brief=brief):
                text = (path / brief).read_text()
                self.assertIn("Polite.", text)
                self.assertNotIn("LOUD", text)
        # A replay: the answer's number cannot be sent on to the coordinator.
        code, _, err = self.hw("say", "unit", "--number", "2")
        self.assertEqual(code, 1)
        self.assertIn("was an answer to HE-2", err)


class MidRunAnswerTests(RunScenario):
    """`hw say --task` while the task runs: the answer reaches a builder before the task can finish."""
    def answer_while(self, worker, text, then="ok"):
        """A sleep for the driver that sends the owner's answer once `worker` is busy, then lets it finish."""
        said = []

        def tick(seconds):
            if worker in self.live and not said:
                with patch("herdworks.drive.detach") as detach:
                    said.append(self.hw("say", "unit", "--task", "HE-2", text))
                detach.assert_not_called()  # a running task takes the answer itself
                self.finish_worker(self.project / "tasks/HE-2", worker.split("he-2-")[1], then)
        return said, tick

    def test_answer_during_the_evidence_stage_reaches_a_builder_before_the_task_is_done(self):
        self.script["evidence"] = ["hang"]
        said, tick = self.answer_while("hw-unit-he-2-evidence-1", "The greeting must be polite.")
        path = drive.create(self.project, "Make hello greet.")
        final = drive.drive(path, interval=0, sleep=tick)
        ((code, out, _),) = said
        self.assertEqual(code, 0)
        self.assertIn("delivered 1 to HE-2: it is running and will not be done before a builder has read this", out)
        self.assertEqual([launch["role"] for launch in self.launched],
                         ["build", "verify", "evidence", "build", "verify", "evidence"])
        brief = (path / "build-2/brief.md").read_text()
        self.assertIn("The greeting must be polite.", brief)
        self.assertIn("make no commit and report READY", brief)
        self.assertEqual((final["state"], final["status"]), ("done", "verified"))
        second = (path / "build-2/report.md").read_text().split()[1]
        self.assertEqual((final["commit"], git(self.repo, "rev-parse", "refs/heads/hw/HE-2")), (second, second))
        self.assertNotEqual((path / "build-1/report.md").read_text().split()[1], second)
        ended = [e["action"] for e in events(path) if e["event"] == "run" and e["action"].split(":")[0] in drive.EXIT]
        self.assertEqual(len(ended), 1, ended)  # it never reported done on the commit built before the answer
        self.assertIn("answer 1 is handed to a new builder", [text for _, text in monitor.timeline(path)])

    def test_answer_during_the_build_goes_to_a_builder_before_anything_is_verified(self):
        self.script["build"] = ["hang"]
        said, tick = self.answer_while("hw-unit-he-2-build-1", "Also keep the old greeting.")
        path = drive.create(self.project, "Make hello greet.")
        final = drive.drive(path, interval=0, sleep=tick)
        self.assertEqual(said[0][0], 0)
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "build", "verify", "evidence"])
        self.assertIn("Also keep the old greeting.", (path / "build-2/brief.md").read_text())
        self.assertNotIn("Also keep the old greeting.", (path / "build-1/brief.md").read_text())
        self.assertEqual(final["state"], "done")

    def test_an_answer_that_needs_no_change_gets_the_same_commit_verified_again_with_it(self):
        self.script["verify"] = ["hang"]
        self.script["build"] = ["ok", "noop"]
        said, tick = self.answer_while("hw-unit-he-2-verify-1", "Yes, lower case is fine.")
        path = drive.create(self.project, "Make hello greet.")
        final = drive.drive(path, interval=0, sleep=tick)
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "build", "verify", "evidence"])
        first = (path / "build-1/report.md").read_text().split()[1]
        self.assertEqual((final["state"], final["status"], final["commit"]), ("done", "verified", first))
        self.assertIn("Yes, lower case is fine.", (path / "build-2/brief.md").read_text())
        self.assertIn("Yes, lower case is fine.", (path / "verify-2/brief.md").read_text())
        self.assertNotIn("Yes, lower case is fine.", (path / "verify-1/brief.md").read_text())

    def test_answer_landing_as_the_run_ends_blocked_on_the_question_is_not_stranded(self):
        self.script["build"] = ["question", "ok"]
        path = drive.create(self.project, "Make hello greet.")
        said, found = [], drive.advance

        def answered_in_the_gap(task):
            step = found(task)
            if step.state == "blocked" and not said:
                # The run has decided to end on the builder's question and has not saved that yet.
                with patch("herdworks.drive.detach") as detach:
                    said.append(self.hw("say", "unit", "--task", "HE-2", "Polite."))
                detach.assert_not_called()
            return step
        with patch("herdworks.drive.advance", side_effect=answered_in_the_gap):
            final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(said[0][0], 0)
        self.assertIn("it is running", said[0][1])
        self.assertEqual(final["state"], "done")
        self.assertIn("Polite.", (path / "build-2/brief.md").read_text())

    def test_answer_before_the_pull_request_means_one_pull_request_for_the_commit_built_with_it(self):
        self.grant_pull_requests()
        self.script["evidence"] = ["hang"]
        said, tick = self.answer_while("hw-unit-he-2-evidence-1", "The greeting must be polite.")
        path = drive.create(self.project, "Make hello greet.")
        final = drive.drive(path, interval=0, sleep=tick)
        self.assertEqual((said[0][0], final["state"], final["pr_url"]), (0, "done", PULL_REQUEST))
        self.assertEqual(len(self.gh_calls()), 1)
        second = (path / "build-2/report.md").read_text().split()[1]
        self.assertEqual((final["commit"], git(self.remote, "rev-parse", "refs/heads/hw/HE-2")), (second, second))
        code, _, err = self.hw("say", "unit", "--task", "HE-2", "One more thing")
        self.assertEqual(code, 1)
        self.assertIn("HE-2 is finished (for review)", err)
        self.assertEqual(len(inbox(self.project)), 1)

    def test_an_answer_on_a_manual_handover_stops_the_pull_request_until_a_builder_and_verifier_have_seen_it(self):
        self.script["verify"] = ["environment", "environment"]
        path, final = self.run_task()
        self.assertIn("hw pr unit HE-2 --manual-verification", final["next_step"])
        with patch("herdworks.drive.detach"):
            self.assertEqual(self.hw("say", "unit", "--task", "HE-2", "I checked the device by hand: fine.")[0], 0)
        self.grant_pull_requests()
        code, _, err = self.hw("pr", "unit", "HE-2", "--manual-verification")
        self.assertEqual(code, 1)
        self.assertIn("answer has not reached a builder yet", err)
        self.assertIn("hw run -p unit --resume HE-2", err)
        self.assertEqual((self.gh_calls(), git(self.remote, "for-each-ref", "--format=%(refname)")), ([], "refs/heads/main"))
        # The command it names works: the builder changes nothing, the same commit is verified again
        # with the answer, and the handover goes through.
        self.script["build"] = ["noop"]
        code, out, _ = self.hw("run", "-p", "unit", "--resume", "HE-2")
        self.assertEqual(code, 0, out)
        final = monitor.record(path)
        self.assertEqual((final["state"], final["status"], final["pr_url"]), ("done", "needs manual verification", PULL_REQUEST))
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "evidence"] * 2)
        self.assertEqual(final["commit"], (path / "build-1/report.md").read_text().split()[1])
        for brief in ("build-2/brief.md", "verify-2/brief.md"):
            self.assertIn("I checked the device by hand: fine.", (path / brief).read_text())
        (call,) = self.gh_calls()
        self.assertEqual(call["args"][-2:], ["--label", "needs-manual-verification"])

    def test_a_no_change_answer_after_a_replaced_fix_builder_is_verified_again_not_called_refused(self):
        # The fix builder commits and dies; its replacement reports that commit, which then passes.
        self.script["build"] = ["ok", "commit-hang", "noop", "noop"]
        self.script["verify"] = ["fail", "hang", "ok"]
        path = drive.create(self.project, "Make hello greet.")
        said = []

        def tick(seconds):
            self.live.discard("hw-unit-he-2-build-2")
            if "hw-unit-he-2-verify-2" in self.live and not said:
                with patch("herdworks.drive.detach"):
                    said.append(self.hw("say", "unit", "--task", "HE-2", "Yes, that is right.")[0])
                self.finish_worker(path, "verify-2")
        final = drive.drive(path, interval=0, sleep=tick)
        self.assertEqual([launch["role"] for launch in self.launched],
                         ["build", "verify", "build", "build", "verify", "build", "verify", "evidence"])
        self.assertEqual((said, final["state"], final["status"]), ([0], "done", "verified"))
        self.assertEqual(final["commit"], (path / "build-3/report.md").read_text().split()[1])
        self.assertIn("Yes, that is right.", (path / "build-4/brief.md").read_text())

    def test_a_coordinator_task_still_refuses_to_verify_an_environment_blocked_commit_again(self):
        (self.notes / "intent.md").write_text("DONE CHECK")
        self.script["verify"] = ["environment"]
        self.script["build"] = ["ok", "hang"]
        for role in ("build", "verify", "evidence"):
            spawn(self.path, role)
            self.idle.clear()
        (self.path / "evidence-1/review.md").write_text("REJECTED\nFinding: proof is thin\n")
        from herdworks.gate import gate
        self.assertFalse(gate(self.path)[0])
        spawn(self.path, "fix")
        with self.assertRaisesRegex(ValueError, "blocked by environment; do not retry"):
            spawn(self.path, "verify")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "evidence", "build"])

    def test_a_stalled_verifier_is_still_ended_when_an_answer_waits_for_a_builder(self):
        self.script["verify"] = ["hang", "ok"]
        path = drive.create(self.project, "Make hello greet.")
        said = []

        def tick(seconds):
            if "hw-unit-he-2-verify-1" in self.live and not said:
                said.append(self.hw("say", "unit", "--task", "HE-2", "Keep it lower case.")[0])
        stalled = [dict(name="hw-unit-he-2-verify-1", stalled=True)]
        with patch("herdworks.drive.probe", side_effect=[[], stalled] + [[]] * 20):
            final = drive.drive(path, interval=0, sleep=tick)
        self.assertEqual((said, final["state"]), ([0], "done"))
        self.assertIn("hw-unit-he-2-verify-1", self.killed)
        self.assertEqual(self.live, set())
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "verify", "build", "verify", "evidence"])
        self.assertIn("Keep it lower case.", (path / "build-2/brief.md").read_text())

    def test_a_builder_that_cannot_start_ends_the_task_blocked_with_the_answer_kept(self):
        self.script["build"] = ["question"]
        path, _ = self.run_task()
        (self.home / "config.json").write_text('{"max_worktrees": 20, "max_sessions_per_task": 1}')
        with patch("herdworks.drive.detach"):
            self.assertEqual(self.hw("say", "unit", "--task", "HE-2", "Polite.")[0], 0)
        final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(final["state"], "blocked")
        self.assertIn("no build worker was started: max_sessions_per_task", final["reason"])
        self.assertIn("answer 1 is saved and goes to a builder when the task continues", final["reason"])
        self.assertEqual(len([e for e in events(path) if e["event"] == "rewind"]), 1)
        (self.home / "config.json").write_text('{"max_worktrees": 20}')
        self.assertEqual(drive.drive(path, interval=0, sleep=lambda seconds: None)["state"], "done")
        self.assertIn("Polite.", (path / "build-2/brief.md").read_text())

    def test_the_answer_and_the_end_state_are_saved_under_the_same_task_lock(self):
        from herdworks.runs import locked
        self.script["build"] = ["question"]
        path = drive.create(self.project, "Make hello greet.")
        seen, found = {}, drive.advance

        def saving_elsewhere(task):
            step = found(task)
            if step.state == "blocked":
                # As if `hw say --task` were in the middle of saving when the run decides to end.
                held = threading.Event()

                def hold():
                    with locked(path):
                        held.set()
                        time.sleep(0.5)
                        seen["state"] = json.loads((path / "status.json").read_text())["state"]
                threading.Thread(target=hold).start()
                held.wait(5)
            return step
        with patch("herdworks.drive.advance", side_effect=saving_elsewhere):
            final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual((seen, final["state"]), ({"state": "running"}, "blocked"))  # the end state waited for the lock
        said = {}
        with locked(path), patch("herdworks.drive.detach"), contextlib.redirect_stdout(io.StringIO()):
            saying = threading.Thread(target=lambda: said.update(code=main(["say", "unit", "--task", "HE-2", "Polite."])))
            saying.start()
            time.sleep(0.5)
            self.assertEqual(inbox(self.project), [])  # and so does the answer
        saying.join(10)
        self.assertEqual((said["code"], len(inbox(self.project))), (0, 1))

    def test_a_stop_or_an_escalation_ends_the_task_as_it_is_and_keeps_the_answer_for_later(self):
        self.script["build"] = ["hang"]
        stopped = drive.create(self.project, "Make hello greet.")
        said = []

        def answer_then_stop(seconds):
            if not said:
                said.append(self.hw("say", "unit", "--task", "HE-2", "Polite.")[0])
                stop(stopped)
        final = drive.drive(stopped, interval=0, sleep=answer_then_stop)
        self.assertEqual((said, final["state"], final["reason"]), ([0], "blocked", "stopped: its workers were ended"))
        self.assertEqual([e for e in events(stopped) if e["event"] == "rewind"], [])
        self.assertEqual(drive.drive(stopped, interval=0, sleep=lambda seconds: None)["state"], "done")
        self.assertIn("Polite.", (stopped / "build-3/brief.md").read_text())
        close(stopped)
        self.launched.clear()
        # An answer sent before the gate gave up is not the decision the escalation asks for.
        self.set_project(checks="exit 3")
        self.script["build"] = ["ok", "hang"]
        escalated = drive.create(self.project, "Second request")
        sent = []

        def tick(seconds):
            if "hw-unit-he-3-build-2" in self.live and not sent:
                sent.append(self.hw("say", "unit", "--task", "HE-3", "Keep it short.")[0])
                self.finish_worker(escalated, "build-2")
        final = drive.drive(escalated, interval=0, sleep=tick)
        self.assertEqual((sent, final["state"]), ([0], "blocked"))
        self.assertIn("refused 2 commits for the same reasons", final["reason"])
        self.assertIn('hw say unit --task HE-3 "YOUR DECISION"', final["next_step"])
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "build"])

    def test_a_failed_resume_says_the_answer_is_saved_and_not_to_send_it_again(self):
        self.script["build"] = ["question", "ok"]
        path, _ = self.run_task()
        with patch("herdworks.drive.detach", side_effect=RuntimeError("the background run did not start")):
            code, out, err = self.hw("say", "unit", "--task", "HE-2", "Polite.")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("answer 1 is saved for HE-2, but the task was not resumed: the background run did not start", err)
        self.assertIn("Do not send it again; continue with: hw run -p unit --resume HE-2", err)
        self.assertEqual(len(inbox(self.project)), 1)
        self.assertEqual(self.hw("run", "-p", "unit", "--resume", "HE-2")[0], 0)
        self.assertIn("Polite.", (path / "build-2/brief.md").read_text())

    def test_resume_waits_for_a_run_that_has_saved_its_end_and_is_still_leaving(self):
        import fcntl
        self.script["build"] = ["question"]
        path, _ = self.run_task()
        with (path / ".driver.lock").open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)  # the ended run, still sending its webhook
            threading.Timer(0.5, lambda: fcntl.flock(held, fcntl.LOCK_UN)).start()
            began = time.monotonic()
            drive.detach(path)
            self.assertGreaterEqual(time.monotonic() - began, 0.4)
        self.assertEqual(len(self.detached), 1)
        # A task that is being driven and has not ended is refused at once, as before.
        with (path / ".driver.lock").open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaisesRegex(ValueError, "already being driven"):
                drive.detach(path)


class DraftPullRequestTests(RunScenario):
    """`hw run` through the real `open_pr`: a bare local remote and the stand-in gh, no GitHub."""
    def test_granted_project_ends_with_the_branch_pushed_and_one_draft_pull_request(self):
        self.grant_pull_requests()
        code, out, err = self.hw("run", "-p", "unit", "Make hello print its build. Done when python3 hello.py prints it.")
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"pull request: {PULL_REQUEST}", out)
        final = json.loads(self.hw("status", "HE-2", "--json")[1])
        head = git(self.repo, "rev-parse", "refs/heads/hw/HE-2")
        self.assertEqual((final["state"], final["stage"], final["status"]), ("done", "done", "for review"))
        self.assertEqual((final["pr_url"], final["commit"]), (PULL_REQUEST, head))
        self.assertEqual(final["reason"], f"verified; draft pull request: {PULL_REQUEST}")
        # The remote gained exactly the task branch, at the verified commit.
        self.assertEqual(git(self.remote, "for-each-ref", "--format=%(refname) %(objectname)").splitlines(),
                         [f"refs/heads/hw/HE-2 {head}", f"refs/heads/main {git(self.repo, 'rev-parse', 'main')}"])
        (call,) = self.gh_calls()
        args = call["args"]
        self.assertEqual(args[:3], ["pr", "create", "--draft"])
        self.assertEqual([args[args.index(flag) + 1] for flag in ("--repo", "--base", "--head")],
                         [str(self.remote), "main", "hw/HE-2"])
        self.assertEqual([line for line in call["body"].splitlines() if line.startswith("## ")],
                         ["## Why", "## Scope", "## Blast Radius", "## Verification"])
        for required in ("Make hello print its build.", "Verdict: PASS", f"Verified commit: {head}",
                         "Evidence review: CONFIRMED", "$ python3 hello.py"):
            self.assertIn(required, call["body"])
        self.assertIn(f"HE-2 for review {head} {PULL_REQUEST}", self.hw("tasks", "unit")[1])
        # Running the finished task again reports the same pull request and opens no second one.
        code, out, _ = self.hw("run", "-p", "unit", "--resume", "HE-2")
        self.assertEqual(code, 0)
        self.assertIn(PULL_REQUEST, out)
        self.assertEqual(len(self.gh_calls()), 1)

    def test_pull_request_failure_is_blocked_with_the_reason_and_the_command_to_retry(self):
        failing = self.root / "failing-gh.sh"
        failing.write_text("#!/bin/sh\necho 'HTTP 401: Bad credentials; token=abc123' >&2\nexit 1\n")
        failing.chmod(0o755)
        self.grant_pull_requests(gh=failing)
        path, final = self.run_task()
        self.assertEqual((final["state"], final["stage"], final["pr_url"]), ("blocked", "pr", None))
        self.assertIn("draft pull request was not opened: draft creation failed", final["reason"])
        self.assertIn("HTTP 401: Bad credentials", final["reason"])
        self.assertNotIn("abc123", json.dumps(final) + (path / "events.jsonl").read_text() + (path / "status.json").read_text())
        self.assertIn("hw pr unit HE-2", final["next_step"])
        self.assertEqual(final["status"], "verified")


class BudgetTests(RunScenario):
    def setUp(self):
        super().setUp()
        self.hook = Hook()
        self.addCleanup(self.hook.close)

    def test_minutes_budget_stops_workers_blocks_and_posts_the_webhook(self):
        self.set_project(webhook=self.hook.url)
        self.script["build"] = ["hang"]
        path = drive.create(self.project, "Request", max_minutes=0.01)
        final = drive.drive(path, interval=0, sleep=lambda seconds: time.sleep(0.7))
        self.assertEqual(final["state"], "blocked")
        self.assertRegex(final["reason"], r"max_minutes budget reached: \d+\.\d of 0\.01 minutes")
        self.assertIn("hw run -p unit --resume HE-2 --max-minutes N", final["next_step"])
        self.assertEqual(self.killed, ["hw-unit-he-2-build-1"])
        self.assertEqual(final["status"], "stopped")
        (sent,) = self.hook.received
        self.assertEqual(sent["type"], "application/json")
        body = sent["body"]
        self.assertEqual((body["event"], body["state"], body["task"], body["project"]), ("budget", "blocked", "HE-2", "unit"))
        self.assertEqual(body["reason"], final["reason"])
        self.assertEqual(body["budget"], {"max_minutes": 0.01, "max_tokens": None})
        self.assertEqual(final["webhook"]["kind"], "budget")
        self.assertTrue(final["webhook"]["ok"])
        # The URL can hold a secret: it reaches the listener and nothing Herdworks writes.
        written = (path / "events.jsonl").read_text() + (path / "status.json").read_text() + json.dumps(final)
        self.assertNotIn("SECRET-TOKEN", written)
        self.assertNotIn("127.0.0.1", written)

    def test_token_budget_uses_only_reported_counts(self):
        self.script["build"] = ["hang"]
        with patch("herdworks.tokens.read", return_value=dict(total=500)):
            path = drive.create(self.project, "Request", max_tokens=100)
            final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(final["state"], "blocked")
        self.assertIn("max_tokens budget reached: 500 of 100 tokens", final["reason"])
        self.assertEqual(self.killed, ["hw-unit-he-2-build-1"])

    def test_cached_input_is_reported_and_never_counted_against_the_token_budget(self):
        self.set_project(webhook=self.hook.url, grants={"push": False, "draft-pr": False, "unsandboxed": True},
                         agents={"builder": {"agent": "opencode", "model": "some/model"}})
        database = self.root / "opencode.db"
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        connection.execute("create table session_v2 (directory text, time_created integer, tokens_input integer, "
                           "tokens_output integer, tokens_reasoning integer, tokens_cache_read integer, tokens_cache_write integer)")
        connection.commit()
        seen = []

        def working(path):
            def tick(seconds):
                if not seen or seen[-1]["task"] != path.name:
                    # The builder's own record: 123 tokens spent, and 400,050 more read from or written to its cache.
                    connection.execute("insert into session_v2 values (?, ?, 100, 20, 3, 400000, 50)",
                                       (str(path / "build-1/wt"), int(time.time() * 1000)))
                    connection.commit()
                    seen.append(monitor.record(path))
                else:
                    seen.append(monitor.record(path))
                    self.finish_worker(path, "build-1")
            return tick
        self.script["build"] = ["hang"]
        with patch("herdworks.tokens.opencode_db", return_value=database):
            # A budget far below the cached count and above the spent count does not stop the task.
            path = drive.create(self.project, "Request", max_tokens=1000)
            final = drive.drive(path, interval=0, sleep=working(path))
            self.assertEqual([(item["state"], item["tokens"]["total"], item["tokens"]["cached"]) for item in seen],
                             [("running", 123, 400050)] * 2)
            self.assertEqual(final["state"], "done")
            self.assertEqual(final["tokens"], dict(build=123, verify="unknown", evidence="unknown", total=123, partial=True,
                                                   cached=400050, includes_cached=False))
            self.assertEqual(self.hook.received[-1]["body"]["tokens"], final["tokens"])
            self.assertRegex(self.hw("status", "HE-2")[1], r"HE-2 done stage=done elapsed=\S+ tokens=123 \(some unknown\) cached=400,050")
            # A budget below the spent count does.
            self.script["build"] = ["hang"]
            path = drive.create(self.project, "Second request", max_tokens=100)
            final = drive.drive(path, interval=0, sleep=working(path))
        self.assertEqual(final["state"], "blocked")
        self.assertEqual(final["reason"], "max_tokens budget reached: 123 of 100 tokens")
        self.assertEqual((self.hook.received[-1]["body"]["event"], self.hook.received[-1]["body"]["tokens"]["cached"]),
                         ("budget", 400050))

    def test_unknown_tokens_never_trip_a_token_budget(self):
        _, final = self.run_task(max_tokens=1)
        self.assertEqual(final["state"], "done")
        self.assertEqual(final["tokens"], dict(build="unknown", verify="unknown", evidence="unknown",
                                               total="unknown", partial=True, cached="unknown", includes_cached=False))

    def test_resume_continues_from_a_commit_the_stopped_builder_left_without_a_report(self):
        self.script["build"] = ["commit-hang", "ok"]
        path = drive.create(self.project, "Request", max_minutes=0.01)
        blocked = drive.drive(path, interval=0, sleep=lambda seconds: time.sleep(0.7))
        self.assertEqual(blocked["state"], "blocked")
        half = git(self.repo, "rev-parse", "refs/heads/hw/HE-2")
        self.assertNotEqual(half, json.loads((path / "task.json").read_text())["base"])
        code, out, _ = self.hw("run", "-p", "unit", "--resume", "HE-2", "--max-minutes", "30")
        self.assertEqual(code, 0, out)
        final = monitor.record(path)
        self.assertEqual(final["state"], "done")
        self.assertEqual(git(self.repo, "rev-parse", f"{final['commit']}~1"), half)

    def test_blocked_time_is_not_counted_and_resume_adds_to_it(self):
        self.script["build"] = ["question", "ok"]
        path, blocked = self.run_task()
        time.sleep(0.3)
        later = monitor.record(path)
        self.assertEqual(later["elapsed_seconds"], blocked["elapsed_seconds"])
        with patch("herdworks.drive.detach"):
            self.hw("say", "unit", "--task", "HE-2", "Polite.")
        final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertGreaterEqual(final["elapsed_seconds"], blocked["elapsed_seconds"])
        self.assertLess(final["elapsed_seconds"] - blocked["elapsed_seconds"], time.time() - later["ended_at"])

    def test_resume_of_a_task_hw_run_does_not_drive_changes_nothing(self):
        before = (self.path / "task.json").read_text()
        code, _, err = self.hw("run", "-p", "unit", "--resume", "HE-1", "--max-minutes", "1")
        self.assertEqual(code, 1)
        self.assertIn("coordinator's task", err)
        self.assertEqual((self.path / "task.json").read_text(), before)
        path, _ = self.run_task()
        close(path)
        code, _, err = self.hw("run", "-p", "unit", "--resume", "HE-2", "--max-minutes", "1")
        self.assertEqual(code, 1)
        self.assertIn("HE-2 is closed", err)
        self.assertNotIn("max_minutes", (path / "task.json").read_text())
        for value in ("inf", "nan"):
            self.assertEqual(self.hw("run", "-p", "unit", "--max-minutes", value, "Request")[0], 1)
        self.assertFalse((self.project / "tasks/HE-3").exists())

    def test_a_bad_budget_setting_is_shown_in_status_and_refused_by_spawn(self):
        (self.notes / "intent.md").write_text("DONE CHECK")
        self.set_project(max_minutes="soon")
        code, out, _ = self.hw("status", "HE-1")
        self.assertEqual(code, 0)
        self.assertIn("budget: invalid (max_minutes must be a positive number)", out)
        self.assertEqual(self.hw("status")[0], 0)
        with self.assertRaisesRegex(ValueError, "max_minutes must be a positive number"):
            spawn(self.path)

    def test_raising_the_budget_resumes_with_a_replacement_and_finishes(self):
        self.script["build"] = ["hang", "ok"]
        path = drive.create(self.project, "Request", max_minutes=0.01)
        drive.drive(path, interval=0, sleep=lambda seconds: time.sleep(0.7))
        code, out, _ = self.hw("run", "-p", "unit", "--resume", "HE-2", "--max-minutes", "30")
        self.assertEqual(code, 0, out)
        final = monitor.record(path)
        self.assertEqual((final["state"], final["budget"]["max_minutes"]), ("done", 30.0))
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "build", "verify", "evidence"])
        self.assertEqual(self.launched[1]["name"], "hw-unit-he-2-build-2")
        self.assertIn("resumed", [e["event"] for e in events(path)])

    def test_webhook_failure_never_stops_the_task(self):
        import socket
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            refused = unused.getsockname()[1]  # closed again on leaving the block, so nothing listens there
        for url, detail in ((f"http://127.0.0.1:{refused}/hook", "URLError"), ("file:///etc/passwd", "ValueError")):
            with self.subTest(url=url):
                self.set_project(webhook=url)
                self.launched.clear()
                path, final = self.run_task()
                self.assertEqual(final["state"], "done")
                self.assertEqual((final["webhook"]["ok"], final["webhook"]["detail"]), (False, detail))
                close(path)
        failing = Hook(status=500)
        self.addCleanup(failing.close)
        self.set_project(webhook=failing.url)
        _, final = self.run_task()
        self.assertEqual((final["state"], final["webhook"]["detail"]), ("done", "HTTP 500"))

    def test_config_output_never_prints_the_webhook_url(self):
        (self.home / "config.json").write_text(json.dumps(dict(webhook=self.hook.url, max_minutes=45)))
        code, out, _ = self.hw("config")
        self.assertEqual((code, json.loads(out)["webhook"], json.loads(out)["max_minutes"]), (0, "(set)", 45))
        self.assertNotIn("SECRET-TOKEN", out)
        self.set_project(webhook=self.hook.url)
        code, out, _ = self.hw("project", "grant", "unit", "--no-push")
        self.assertEqual((code, json.loads(out)["webhook"]), (0, "(set)"))
        self.assertNotIn("SECRET-TOKEN", out)
        path = drive.create(self.project, "Request")
        self.assertEqual(monitor.record(path)["budget"], {"max_minutes": 45, "max_tokens": None})

    def test_done_posts_the_webhook_with_branch_and_commit(self):
        self.set_project(webhook=self.hook.url)
        _, final = self.run_task()
        (sent,) = self.hook.received
        self.assertEqual((sent["body"]["event"], sent["body"]["branch"], sent["body"]["commit"]),
                         ("done", "hw/HE-2", final["commit"]))
        self.assertEqual(sent["body"]["reason"], f"verified: commit {final['commit']} on branch hw/HE-2. No pull request, "
                                                 "because the Project has not granted push, draft-pr")
        # Nothing sent off the machine names a local folder: not the repository, not the Herdworks home.
        self.assertNotIn(str(self.root), json.dumps(sent["body"]))

    def test_spawn_refuses_a_coordinator_task_that_is_over_budget(self):
        (self.notes / "intent.md").write_text("DONE CHECK")
        self.set_project(max_minutes=1)
        data = json.loads((self.path / "task.json").read_text())
        (self.path / "task.json").write_text(json.dumps(dict(data, created_at=time.time() - 120)))
        with self.assertRaisesRegex(ValueError, "max_minutes budget reached: 2.0 of 1 minutes"):
            spawn(self.path)
        self.assertEqual(self.launched, [])
        current = monitor.record(self.path)
        self.assertEqual((current["state"], current["driver"]), ("blocked", "coordinator"))
        self.set_project(max_minutes=-5)
        with self.assertRaisesRegex(ValueError, "max_minutes must be a positive number"):
            spawn(self.path)


class StatusRecordTests(RunScenario):
    def test_record_follows_stage_state_last_action_and_elapsed_while_running(self):
        self.script["build"] = ["hang"]
        path = drive.create(self.project, "Request line one\nmore")
        seen = []

        def look(seconds):
            seen.append(monitor.record(path))
            if len(seen) == 2:
                self.build(path / "build-1/wt", "ok")
                self.live.clear()
        final = drive.drive(path, interval=0, sleep=look)
        first = seen[0]
        self.assertEqual((first["state"], first["stage"], first["request"]), ("running", "build", "Request line one"))
        self.assertEqual(first["last_action"], "started build hw-unit-he-2-build-1")
        self.assertEqual(first["sessions"][0]["state"], "working")
        self.assertGreaterEqual(seen[1]["elapsed_seconds"], first["elapsed_seconds"])
        self.assertEqual(final["last_action"].split(":")[0], "done")
        stages = [e["action"] for e in events(path) if e.get("event") == "run"]
        self.assertEqual(len(stages), 1)

    def test_tokens_come_from_the_agents_own_records_per_role(self):
        database = self.root / "opencode.db"
        connection = sqlite3.connect(database)
        connection.execute("create table session_v2 (directory text, time_created integer, tokens_input integer, "
                           "tokens_output integer, tokens_reasoning integer, tokens_cache_read integer, tokens_cache_write integer)")
        path, _ = self.run_task()
        now = int(time.time() * 1000)
        connection.execute("insert into session_v2 values (?, ?, 100, 20, 3, 4000, 0)", (str(path / "build-1/wt"), now))
        connection.execute("insert into session_v2 values (?, ?, 1, 1, 1, 1, 1)", (str(path / "build-1/wt"), now))
        # A session from an earlier use of the same folder path is not this worker's.
        connection.execute("insert into session_v2 values (?, ?, 9, 9, 9, 9, 9)", (str(path / "build-1/wt"), now - 86400000))
        connection.commit()
        connection.close()
        events_file = path / "events.jsonl"
        events_file.write_text(events_file.read_text().replace('"agent": "codex"', '"agent": "opencode"'))
        with patch("herdworks.tokens.opencode_db", return_value=database):
            current = monitor.record(path)
        # The totals are input + output + reasoning; the 4,002 cached tokens stand beside them, in no total.
        self.assertEqual(current["tokens"], dict(build=126, verify="unknown", evidence="unknown", total=126, partial=True,
                                                 cached=4002, includes_cached=False))
        self.assertEqual(current["sessions"][0]["tokens"],
                         dict(input=101, output=21, reasoning=4, cache_read=4001, cache_write=1, total=126))
        self.assertIn("tokens=126 (some unknown) cached=4,002", monitor.headline(current))
        self.assertRegex("\n".join(monitor.render(current)), r"build +opencode \S+ tokens=126 cached=4,002 finished")
        self.assertIsNone(tokens.read("some-other-agent", path))

    def test_codex_reader_sums_threads_by_folder(self):
        home = self.root / "codex"
        home.mkdir()
        connection = sqlite3.connect(home / "state_5.sqlite")
        connection.execute("create table threads (cwd text, created_at integer, tokens_used integer)")
        connection.executemany("insert into threads values (?, ?, ?)",
                               [("/w/a", 5000, 10), ("/w/a", 5100, 5), ("/w/a", 100, 99), ("/w/b", 5000, 7)])
        connection.commit()
        connection.close()
        with patch("herdworks.tokens.codex_db", return_value=home / "state_5.sqlite"):
            used = tokens.read("codex", "/w/a", since=5000)
            self.assertIsNone(tokens.read("codex", "/w/none", since=5000))
        # Codex keeps one figure, tokens_used, with cached input inside it: it is passed on and labelled as that.
        self.assertEqual(used, dict(total=15, includes_cached=True))
        summary = monitor.token_summary([dict(role="build", tokens=used)])
        self.assertEqual(summary, dict(build=15, total=15, partial=False, cached="unknown", includes_cached=True))
        self.assertEqual(monitor.spent(used), "tokens=15 (Codex's figure, cached input included)")
        # A total that also holds opencode sessions says only that Codex figures are in it.
        mixed = monitor.token_summary([dict(role="build", tokens=used),
                                       dict(role="verify", tokens=dict(input=5, output=2, reasoning=1, cache_read=90, cache_write=0, total=8))])
        self.assertEqual(monitor.spent(mixed), "tokens=23 (with Codex's figures, which count cached input) cached=90")

    def test_a_run_whose_driver_died_reads_as_blocked_with_the_resume_command(self):
        path = drive.create(self.project, "Request")
        monitor.write(path, pid=2 ** 22 + 12345)
        current = monitor.record(path)
        self.assertEqual(current["state"], "blocked")
        self.assertIn("no longer running", current["reason"])
        self.assertIn("hw run -p unit --resume HE-2", current["next_step"])
        # A live process that merely has the saved pid is not the driver: only the held lock says so.
        saved = dict(json.loads((path / "status.json").read_text()), pid=os.getpid(), updated_at=time.time() - 300)
        (path / "status.json").write_text(json.dumps(saved))
        self.assertEqual(monitor.record(path)["state"], "blocked")
        with (path / ".driver.lock").open("a") as held:
            import fcntl
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertEqual(monitor.record(path)["state"], "running")

    def test_coordinator_task_gets_a_derived_record_and_the_tree_shows_it(self):
        append_event(self.path, dict(event="session", address="t2", name="hw-unit-he-1-build-1", role="build",
                                     agent="codex", folder="build-1", started_at=time.time() - 90, stuck_after_minutes=60))
        self.live.add("t2")
        current = monitor.record(self.path)
        self.assertEqual((current["driver"], current["state"], current["stage"], current["status"]),
                         ("coordinator", "running", "build", "in progress"))
        self.assertEqual(current["last_action"], "started build hw-unit-he-1-build-1")
        self.assertEqual(current["tokens"]["total"], "unknown")
        code, out, _ = self.hw("status", "unit")
        self.assertRegex(out, r"HE-1 in progress stage=build elapsed=\d+m\d\ds tokens=unknown")
        code, out, _ = self.hw("status", "--json")
        self.assertEqual([item["task"] for item in json.loads(out)], ["HE-1"])

    def test_plain_status_shows_a_run_task_as_its_record_does_with_the_reason_and_next_step(self):
        self.script["build"] = ["question", "hang"]
        asking, _ = self.run_task("Greet the user")
        over = drive.create(self.project, "Second request", max_minutes=0.01)
        drive.drive(over, interval=0, sleep=lambda seconds: time.sleep(0.7))
        _, done = self.run_task("Third request")
        stop(self.path)  # a coordinator's task that was stopped stays out of the tree, as before
        self.assertEqual([monitor.record(path)["status"] for path in (asking, over)], ["in progress", "stopped"])
        code, out, _ = self.hw("status", "unit")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"\|-- HE-2 blocked stage=build elapsed=\S+ tokens=unknown\n"
                              r"\|   \|-- reason: the builder needs a decision: Should the greeting be loud or polite\?\n"
                              r'\|   \|-- next: hw say unit --task HE-2 "YOUR DECISION"\n')
        self.assertRegex(out, r"\|-- HE-3 blocked stage=build elapsed=\S+ tokens=unknown\n"
                              r"\|   \|-- reason: max_minutes budget reached: \d+\.\d of 0\.01 minutes\n"
                              r"\|   \|-- next: raise the budget and continue: hw run -p unit --resume HE-3 --max-minutes N")
        self.assertRegex(out, r"\|-- HE-4 done stage=done elapsed=\S+ tokens=unknown\n"
                              rf"\|   \|-- result: verified: commit {done['commit']} on branch hw/HE-4")
        self.assertNotIn("HE-1", out)
        self.assertNotIn("in progress", out)

    def test_watch_follows_until_a_terminal_state_and_reports_it_in_the_exit_code(self):
        self.script["build"] = ["hang"]
        path = drive.create(self.project, "Request", max_minutes=0.001)
        waits = []

        def tick(seconds):
            waits.append(seconds)
            drive.drive(path, interval=0, sleep=lambda s: time.sleep(0.1))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = follow(path, sleep=tick)
        self.assertEqual((code, len(waits)), (2, 1))
        lines = out.getvalue().splitlines()
        self.assertRegex(lines[0], r"^\d\d:\d\d:\d\d HE-2 running stage=queued")
        self.assertIn("HE-2 blocked", out.getvalue())
        self.assertIn("next: raise the budget and continue: hw run -p unit --resume HE-2", out.getvalue())
        code, out, _ = self.hw("watch", "--json")
        self.assertEqual((code, json.loads(out.splitlines()[-1])["task"]), (2, "HE-2"))

    def test_status_names_an_unknown_task(self):
        code, _, err = self.hw("status", "HE-9")
        self.assertEqual(code, 1)
        self.assertIn("no task HE-9", err)


class MessageRoutingTests(RunScenario):
    def test_task_message_to_a_closed_task_is_refused_with_the_next_step_and_not_recorded(self):
        path, _ = self.run_task()
        close(path, reason="pull request merged")
        code, out, err = self.hw("say", "unit", "--task", "HE-2", "it still prints the wrong thing")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("HE-2 is closed (pull request merged)", err)
        self.assertIn("was not delivered", err)
        self.assertIn('Next step: start a follow-up task with: hw run -p unit "..."', err)
        self.assertEqual(inbox(self.project), [])

    def test_task_message_to_an_unknown_task_is_refused_with_the_next_step(self):
        code, _, err = self.hw("say", "unit", "--task", "HE-99", "hello?")
        self.assertEqual(code, 1)
        self.assertIn("HE-99 is not a task of Project unit", err)
        self.assertIn("hw tasks unit", err)
        self.assertEqual(inbox(self.project), [])

    def test_a_message_that_only_mentions_a_task_goes_to_the_coordinator_as_written(self):
        closed, _ = self.run_task()
        close(closed, reason="pull request merged")
        self.script["build"] = ["question"]
        asking, _ = self.run_task("Second request")
        texts = ["Like HE-2, add tests for the greeting", "Please look at HE-99 and MSG-4", "For HE-3: polite",
                 "how is HE-1 going?"]
        with patch("herdworks.hc.get", return_value=self.coordinator()), patch("herdworks.hc.call") as call:
            for number, text in enumerate(texts, 1):
                with self.subTest(text=text):
                    self.assertEqual(self.hw("say", "unit", text), (0, f"delivered {number}\n", ""))
                    self.assertEqual(call.call_args.args, ("send", "t1", f"MESSAGE {number}\n{text}"))
        self.assertEqual([(m["text"], "task" in m) for m in inbox(self.project)], [(text, False) for text in texts])
        # Mentioning a hw run task is not an answer to it: it still waits for the owner's --task message.
        self.assertEqual(drive.drive(asking, interval=0, sleep=lambda seconds: None)["state"], "blocked")
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "verify", "evidence", "build"])

    def test_message_about_a_coordinator_task_reaches_the_coordinator_with_its_task(self):
        with patch("herdworks.hc.get", return_value=self.coordinator()), patch("herdworks.hc.call") as call:
            code, out, _ = self.hw("say", "unit", "--task", "HE-1", "use the blue one")
            self.assertEqual((code, out), (0, "delivered 1\n"))
            call.assert_called_once_with("send", "t1", "MESSAGE 1 about HE-1\nuse the blue one")
        self.assertEqual(inbox(self.project)[0]["task"], "HE-1")

    def test_a_finished_run_task_refuses_a_task_message_and_names_the_follow_up(self):
        self.script["build"] = ["question", "ok"]
        path, _ = self.run_task()
        with patch("herdworks.drive.detach"):
            self.assertEqual(self.hw("say", "unit", "--task", "HE-2", "polite")[0], 0)
        self.assertEqual((path.parents[1] / "coordinator/tasks/HE-2/answers/1.md").read_text(), "polite")
        final = drive.drive(path, interval=0, sleep=lambda seconds: None)
        self.assertEqual(final["state"], "done")
        code, _, err = self.hw("say", "unit", "--task", "HE-2", "one more thing")
        self.assertEqual(code, 1)
        self.assertIn("HE-2 is finished (verified)", err)
        self.assertIn("hw run -p unit", err)
        self.assertEqual(len(inbox(self.project)), 1)
