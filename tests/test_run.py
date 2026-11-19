import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
import sqlite3
import threading
import time
from unittest.mock import patch
from herdworks import drive, monitor, tokens
from herdworks.cli import follow, main
from herdworks.pickup import close
from herdworks.projects import read_project
from herdworks.runs import append_event, events, git
from herdworks.spawn import spawn
from herdworks.talk import inbox
from tests.support import RunCase, write_claims


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
        self.live, self.killed, self.launched = set(), [], []
        self.script = {"build": [], "verify": [], "evidence": []}
        for target, effect in (("launch", self.launch), ("get", self.get), ("call", self.call),
                               ("sessions", lambda: [dict(address=name) for name in sorted(self.live)]),
                               ("require_owner", lambda: None)):
            patcher = patch(f"herdworks.hc.{target}", side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)

    def launch(self, **kwargs):
        role, cwd = kwargs["role"], kwargs["cwd"]
        self.launched.append(kwargs)
        act = self.script[role].pop(0) if self.script[role] else "ok"
        if act == "hang":
            self.live.add(kwargs["name"])
        else:
            getattr(self, role)(cwd, act)
        return dict(address=kwargs["name"], name=kwargs["name"], first_message={"sent": True})

    def stamp(self, file):
        now = time.time()
        os.utime(file, (now, now))

    def build(self, wt, act):
        report = wt.parent / "report.md"
        if act == "question":
            report.write_text("BLOCKED\nShould the greeting be loud or polite?\n")
        else:
            (wt / "hello.py").write_text(f"print('{wt.parent.name}')\n")
            git(wt, "add", ".")
            git(wt, "commit", "-m", f"feat: {wt.parent.name}")
            report.write_text(f"READY {git(wt, 'rev-parse', 'HEAD')}\n")
        self.stamp(report)

    def verify(self, wt, act):
        folder = wt.parent
        commit = git(wt, "rev-parse", "HEAD")
        write_claims(folder, "DISPROVED" if act == "fail" else "PROVED")
        (folder / "evidence/commands.json").write_text(json.dumps([dict(command="python3 hello.py", output="ok\n")]))
        (folder / "verdict.md").write_text(f"{'FAIL' if act == 'fail' else 'PASS'}\nCommit: {commit}\nFinding: wrong output\n")
        self.stamp(folder / "verdict.md")

    def evidence(self, work, act):
        (work.parent / "review.md").write_text("CONFIRMED\n")
        self.stamp(work.parent / "review.md")

    def get(self, name):
        if name in self.live:
            return dict(state="live", status="working", address=name, name=name,
                        labels=dict(hw=self.labels.get(name, "")))
        return dict(state="finished", address=name, name=name)

    @property
    def labels(self):
        return {launch["name"]: launch["identity"] for launch in self.launched}

    def call(self, *args):
        if args[0] == "kill":
            self.live.discard(args[1])
            self.killed.append(args[1])
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
        self.assertFalse((self.project / "coordinator.json").read_text().count("hw-unit-he-2"))
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

    def test_granted_project_ends_with_the_draft_pull_request(self):
        self.set_project(grants={"push": True, "draft-pr": True})
        with patch("herdworks.drive.open_pr", return_value="https://github.com/o/r/pull/7") as opened:
            path, final = self.run_task()
        opened.assert_called_once_with(path, manual_verification=False)
        self.assertEqual(final["state"], "done")
        self.assertIn("draft pull request: https://github.com/o/r/pull/7", final["reason"])

    def test_pull_request_failure_is_blocked_with_the_reason_and_the_command_to_retry(self):
        self.set_project(grants={"push": True, "draft-pr": True})
        with patch("herdworks.drive.open_pr", side_effect=RuntimeError("draft creation failed; token=abc123")):
            _, final = self.run_task()
        self.assertEqual(final["state"], "blocked")
        self.assertIn("draft pull request was not opened", final["reason"])
        self.assertNotIn("abc123", json.dumps(final))
        self.assertIn("hw pr unit HE-2", final["next_step"])

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
            code, _, err = self.hw("spawn", "unit", "HE-2", "build")
        self.assertEqual(code, 1)
        self.assertIn("driven by hw run", err)
        self.assertEqual(events(path), [])


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
        self.assertRegex(final["reason"], r"max_minutes budget reached: 0\.0 of 0\.01 minutes")
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

    def test_unknown_tokens_never_trip_a_token_budget(self):
        _, final = self.run_task(max_tokens=1)
        self.assertEqual(final["state"], "done")
        self.assertEqual(final["tokens"], dict(build="unknown", verify="unknown", evidence="unknown",
                                               total="unknown", partial=True))

    def test_raising_the_budget_resumes_with_a_replacement_and_finishes(self):
        self.script["build"] = ["hang", "ok"]
        path = drive.create(self.project, "Request", max_minutes=0.01)
        drive.drive(path, interval=0, sleep=lambda seconds: time.sleep(0.7))
        with patch("herdworks.drive.drive", wraps=lambda p, announce=None: drive._drive(p, 0, announce, lambda s: None)):
            code, out, _ = self.hw("run", "-p", "unit", "--resume", "HE-2", "--max-minutes", "30")
        self.assertEqual(code, 0, out)
        final = monitor.record(path)
        self.assertEqual((final["state"], final["budget"]["max_minutes"]), ("done", 30.0))
        self.assertEqual([launch["role"] for launch in self.launched], ["build", "build", "verify", "evidence"])
        self.assertEqual(self.launched[1]["name"], "hw-unit-he-2-build-2")
        self.assertIn("resumed", [e["event"] for e in events(path)])

    def test_webhook_failure_never_stops_the_task(self):
        for url, detail in ((self.hook.url.replace(str(self.hook.server.server_port), "9"), "URLError"),
                            ("file:///etc/passwd", "ValueError")):
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

    def test_done_posts_the_webhook_with_branch_and_commit(self):
        self.set_project(webhook=self.hook.url)
        _, final = self.run_task()
        (sent,) = self.hook.received
        self.assertEqual((sent["body"]["event"], sent["body"]["branch"], sent["body"]["commit"]),
                         ("done", "hw/HE-2", final["commit"]))

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
        connection.execute("create table session_v2 (directory text, tokens_input integer, tokens_output integer, "
                           "tokens_reasoning integer, tokens_cache_read integer, tokens_cache_write integer)")
        path, _ = self.run_task()
        connection.execute("insert into session_v2 values (?, 100, 20, 3, 4000, 0)", (str(path / "build-1/wt"),))
        connection.execute("insert into session_v2 values (?, 1, 1, 1, 1, 1)", (str(path / "build-1/wt"),))
        connection.commit()
        connection.close()
        events_file = path / "events.jsonl"
        events_file.write_text(events_file.read_text().replace('"agent": "codex"', '"agent": "opencode"'))
        with patch("herdworks.tokens.opencode_db", return_value=database):
            current = monitor.record(path)
        self.assertEqual(current["tokens"], dict(build=4128, verify="unknown", evidence="unknown", total=4128, partial=True))
        self.assertEqual(current["sessions"][0]["tokens"],
                         dict(input=101, output=21, reasoning=4, cache_read=4001, cache_write=1, total=4128))
        self.assertIn("tokens=4,128 (some unknown)", monitor.headline(current))
        self.assertIsNone(tokens.read("some-other-agent", path))

    def test_codex_reader_sums_threads_by_folder(self):
        home = self.root / "codex"
        home.mkdir()
        connection = sqlite3.connect(home / "state_5.sqlite")
        connection.execute("create table threads (cwd text, tokens_used integer)")
        connection.executemany("insert into threads values (?, ?)", [("/w/a", 10), ("/w/a", 5), ("/w/b", 7)])
        connection.commit()
        connection.close()
        with patch.dict(os.environ, CODEX_HOME=str(home)), patch("herdworks.tokens.codex_db", wraps=None) as unused:
            unused.side_effect = lambda: home / "state_5.sqlite"
            self.assertEqual(tokens.read("codex", "/w/a"), dict(total=15))
            self.assertIsNone(tokens.read("codex", "/w/none"))

    def test_a_run_whose_driver_died_reads_as_blocked_with_the_resume_command(self):
        path = drive.create(self.project, "Request")
        monitor.write(path, pid=2 ** 22 + 12345)
        current = monitor.record(path)
        self.assertEqual(current["state"], "blocked")
        self.assertIn("no longer running", current["reason"])
        self.assertIn("hw run -p unit --resume HE-2", current["next_step"])

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
    def coordinator(self):
        return dict(name="hw-unit-coord", address="t1", state="live", status=dict(state="idle"),
                    cwd=str(self.project / "coordinator"), labels=dict(hw="project:unit"))

    def test_message_naming_a_closed_task_is_refused_with_the_next_step_and_not_recorded(self):
        path, _ = self.run_task()
        close(path, reason="pull request merged")
        for args in (["say", "unit", "HE-2 still prints the wrong thing"],
                     ["say", "unit", "--task", "HE-2", "it still prints the wrong thing"]):
            with self.subTest(args=args):
                code, out, err = self.hw(*args)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("HE-2 is closed (pull request merged)", err)
                self.assertIn("was not delivered", err)
                self.assertIn('Next step: start a follow-up task with: hw run -p unit "..."', err)
        self.assertEqual(inbox(self.project), [])

    def test_message_naming_an_unknown_task_is_refused_and_new_sends_it_anyway(self):
        code, _, err = self.hw("say", "unit", "--task", "HE-99", "hello?")
        self.assertEqual(code, 1)
        self.assertIn("HE-99 is not a task of Project unit", err)
        self.assertIn("hw tasks unit", err)
        code, _, err = self.hw("say", "unit", "Please look at HE-99 and MSG-4")
        self.assertEqual(code, 1)
        self.assertIn("HE-99 is not a task", err)
        self.assertIn("--new", err)
        self.assertEqual(inbox(self.project), [])
        with patch("herdworks.hc.get", return_value=self.coordinator()), patch("herdworks.hc.call") as call:
            code, out, _ = self.hw("say", "unit", "--new", "Build what HE-99 would have been")
        self.assertEqual((code, out), (0, "delivered 1\n"))
        call.assert_called_once_with("send", "t1", "MESSAGE 1\nBuild what HE-99 would have been")

    def test_message_about_a_coordinator_task_reaches_the_coordinator_with_its_task(self):
        with patch("herdworks.hc.get", return_value=self.coordinator()), patch("herdworks.hc.call") as call:
            code, out, _ = self.hw("say", "unit", "--task", "HE-1", "use the blue one")
            self.assertEqual((code, out), (0, "delivered 1\n"))
            call.assert_called_once_with("send", "t1", "MESSAGE 1 about HE-1\nuse the blue one")
            self.assertEqual(self.hw("say", "unit", "how is HE-1 going?")[0], 0)
        self.assertEqual(inbox(self.project)[0]["task"], "HE-1")

    def test_run_task_messages_need_task_and_a_finished_one_names_the_follow_up(self):
        self.script["build"] = ["question"]
        path, _ = self.run_task()
        code, _, err = self.hw("say", "unit", "For HE-2: polite")
        self.assertEqual(code, 1)
        self.assertIn('hw say unit --task HE-2 "..."', err)
        self.assertEqual(inbox(self.project), [])
        self.script["build"] = ["ok"]
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
