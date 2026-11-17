import json
from unittest.mock import patch
from herdworks.runs import append_event, events, git
from herdworks.spawn import spawn
from tests.support import RunCase


class SpawnTests(RunCase):
    def setUp(self):
        super().setUp()
        (self.root / "briefs").mkdir()
        (self.root / "briefs/build.md").write_text("BUILD CONTRACT")
        (self.notes / "intent.md").write_text("DONE CHECK")
        append_event(self.path, {"event": "session", "role": "coordinator", "address": "t1"})

    @patch("herdworks.hc.call")
    def test_worker_brief_launch_and_record(self, call):
        call.return_value = {"address": "t2", "name": "hw-unit-he-1-build-1", "parent": "t1",
                             "first_message": {"sent": True}}
        spawn(self.path, root=self.root)
        brief = (self.path / "build-1/brief.md").read_text()
        for source in ("BUILD CONTRACT", "house rules: all", "house rules: build", "ORIGINAL REQUEST", "DONE CHECK"):
            self.assertIn(source, brief)
        args = list(map(str, call.call_args.args))
        self.assertIn("hw-builder", args)
        self.assertIn("hw-unit-he-1-build-1", args)
        self.assertIn("hw=unit:HE-1", args)
        self.assertIn("role=build", args)
        self.assertEqual(args[args.index("--parent") + 1], "t1")
        self.assertEqual(git(self.path / "build-1/wt", "branch", "--show-current"), "hw/HE-1")
        self.assertFalse((self.path / "build-1/launch-pending.json").exists())
        event = events(self.path)[-1]
        self.assertEqual(event["name"], "hw-unit-he-1-build-1")
        self.assertEqual(event["stuck_after_minutes"], 60)
        self.assertGreater(event["started_at"], 0)

    @patch("herdworks.hc.call")
    def test_thirteenth_worker_refused_without_side_effect(self, call):
        for number in range(12):
            append_event(self.path, {"event": "session", "role": "build", "name": f"worker-{number}"})
        with self.assertRaisesRegex(ValueError, "budget"):
            spawn(self.path, root=self.root)
        call.assert_not_called()
        self.assertFalse((self.path / "build-1").exists())

    def assert_no_worker_resources(self, folder):
        self.assertFalse((folder / "brief.md").exists())
        self.assertFalse((folder / "wt").exists())
        self.assertNotIn("refs/heads/hw/HE-1",
                         git(self.repo, "for-each-ref", "--format=%(refname)").splitlines())
        self.assertNotIn(str(folder / "wt"), git(self.repo, "worktree", "list", "--porcelain"))

    @patch("herdworks.hc.launch")
    def test_partial_worktree_failure_rolls_back_and_retries(self, launch):
        def fail_after_add(repo, *args, **kwargs):
            result = git(repo, *args, **kwargs)
            if args[:2] == ("worktree", "add"):
                raise RuntimeError("worktree setup failed")
            return result

        with patch("herdworks.spawn.git", side_effect=fail_after_add):
            with self.assertRaisesRegex(RuntimeError, "worktree setup failed"):
                spawn(self.path, root=self.root)
        folder = self.path / "build-1"
        self.assert_no_worker_resources(folder)
        self.assertFalse(folder.exists())
        launch.assert_not_called()
        launch.return_value = {"address": "t2", "name": "hw-unit-he-1-build-1", "parent": "t1",
                               "first_message": {"sent": True}}
        self.assertEqual(spawn(self.path, root=self.root)["address"], "t2")
        self.assertEqual(git(folder / "wt", "branch", "--show-current"), "hw/HE-1")
        self.assertEqual(events(self.path)[-1]["address"], "t2")

    @patch("herdworks.hc.launch")
    def test_launch_not_started_rolls_back_and_retries_preserving_folder(self, launch):
        folder = self.path / "build-1"
        folder.mkdir()
        (folder / "existing.txt").write_text("keep")
        launch.side_effect = FileNotFoundError("hc executable unavailable")
        with self.assertRaisesRegex(FileNotFoundError, "hc executable unavailable"):
            spawn(self.path, root=self.root)
        self.assert_no_worker_resources(folder)
        self.assertEqual((folder / "existing.txt").read_text(), "keep")
        self.assertEqual(list(folder.iterdir()), [folder / "existing.txt"])
        launch.side_effect = None
        launch.return_value = {"address": "t2", "name": "hw-unit-he-1-build-1", "parent": "t1",
                               "first_message": {"sent": True}}
        self.assertEqual(spawn(self.path, root=self.root)["address"], "t2")
        self.assertEqual(git(folder / "wt", "branch", "--show-current"), "hw/HE-1")
        self.assertEqual((folder / "existing.txt").read_text(), "keep")

    @patch("herdworks.hc.launch", side_effect=RuntimeError("core reply lost"))
    def test_uncertain_launch_is_detected_without_starting_duplicate(self, launch):
        with self.assertRaisesRegex(RuntimeError, "core reply lost"):
            spawn(self.path, root=self.root)
        folder = self.path / "build-1"
        self.assertTrue((folder / "launch-pending.json").exists())
        self.assertTrue((folder / "brief.md").exists())
        self.assertEqual(git(folder / "wt", "branch", "--show-current"), "hw/HE-1")
        with patch("herdworks.hc.get", side_effect=RuntimeError("core unavailable; uncertain")):
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                spawn(self.path, root=self.root)
        self.assertEqual(launch.call_count, 1)

    @patch("herdworks.hc.launch")
    def test_existing_branch_survives_failed_setup(self, launch):
        git(self.repo, "branch", "hw/HE-1")
        base = git(self.repo, "rev-parse", "hw/HE-1")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            spawn(self.path, root=self.root)
        self.assertEqual(git(self.repo, "rev-parse", "hw/HE-1"), base)
        self.assertFalse((self.path / "build-1").exists())
        launch.assert_not_called()

    @patch("herdworks.hc.launch")
    def test_started_session_is_retained_when_first_message_fails(self, launch):
        launch.return_value = {"address": "t2", "name": "hw-unit-he-1-build-1", "parent": "t1",
                               "first_message": {"sent": False}}
        with self.assertRaisesRegex(RuntimeError, "first message"):
            spawn(self.path, root=self.root)
        self.assertTrue((self.path / "build-1/wt/.git").exists())
        self.assertEqual(events(self.path)[-1]["address"], "t2")
        with self.assertRaisesRegex(RuntimeError, "already started"):
            spawn(self.path, root=self.root)
        self.assertEqual(launch.call_count, 1)

    @patch("herdworks.hc.launch")
    def test_retry_reconciles_process_death_after_worktree_creation(self, launch):
        def die_after_add(repo, *args, **kwargs):
            result = git(repo, *args, **kwargs)
            if args[:2] == ("worktree", "add"):
                raise KeyboardInterrupt("simulate process death without handler")
            return result

        with patch("herdworks.spawn.git", side_effect=die_after_add):
            with self.assertRaises(KeyboardInterrupt):
                spawn(self.path, root=self.root)
        self.assertTrue((self.path / "build-1/wt/.git").exists())
        launch.return_value = {"address": "t2", "name": "hw-unit-he-1-build-1", "first_message": {"sent": True}}
        spawn(self.path, root=self.root)
        self.assertEqual(len([e for e in events(self.path) if e.get("role") == "build"]), 1)
        self.assertFalse(list(self.path.glob(".setup-*.json")))
        self.assertEqual(git(self.repo, "for-each-ref", "--format=%(refname)", "refs/hw-setup"), "")

    @patch("herdworks.hc.launch", side_effect=RuntimeError("reply lost"))
    def test_retry_recovers_launched_session_without_duplicate(self, launch):
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            spawn(self.path, root=self.root)
        observed = dict(address="t2", name="hw-unit-he-1-build-1", state="live", labels={"hw": "unit:HE-1"},
                        cwd=str(self.path / "build-1/wt"), first_message={"sent": True})
        with patch("herdworks.hc.get", return_value=observed):
            with self.assertRaisesRegex(RuntimeError, "already started"):
                spawn(self.path, root=self.root)
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(events(self.path)[-1]["address"], "t2")
        self.assertFalse(list(self.path.glob(".setup-*.json")))

    @patch("herdworks.hc.launch")
    def test_branch_changed_during_rollback_is_not_deleted(self, launch):
        def fail_after_branch_moves(repo, *args, **kwargs):
            result = git(repo, *args, **kwargs)
            if args[:2] == ("worktree", "add"):
                self.commit()
                git(self.repo, "update-ref", "refs/heads/hw/HE-1", git(self.repo, "rev-parse", "HEAD"))
                raise RuntimeError("worktree setup failed")
            return result
        with patch("herdworks.spawn.git", side_effect=fail_after_branch_moves):
            with self.assertRaises(RuntimeError):
                spawn(self.path, root=self.root)
        self.assertEqual(git(self.repo, "rev-parse", "hw/HE-1"), git(self.repo, "rev-parse", "HEAD"))
        launch.assert_not_called()

    @patch("herdworks.hc.launch")
    def test_up_reconciles_partial_worker_before_fresh_coordinator(self, launch):
        from herdworks.talk import up
        def die_after_add(repo, *args, **kwargs):
            result = git(repo, *args, **kwargs)
            if args[:2] == ("worktree", "add"):
                raise KeyboardInterrupt("process died")
            return result
        with patch("herdworks.spawn.git", side_effect=die_after_add):
            with self.assertRaises(KeyboardInterrupt):
                spawn(self.path, root=self.root)
        launch.return_value = dict(name="hw-unit-coord", address="t3", first_message={"sent": True})
        with patch("herdworks.hc.get", return_value={"state": "missing"}):
            up(self.project, self.root)
        self.assert_no_worker_resources(self.path / "build-1")
        self.assertFalse(list(self.path.glob(".setup-*.json")))
        self.assertEqual(json.loads((self.project / "coordinator.json").read_text())["address"], "t3")

    @patch("herdworks.hc.launch")
    def test_long_project_and_task_ids_fit_core_session_names(self, launch):
        import re
        from herdworks.runs import read_task
        data = read_task(self.path)
        data.update(project="abcdefghijkl", id="HE-999999")
        (self.path / "task.json").write_text(json.dumps(data))
        launch.return_value = dict(address="t2", first_message=dict(sent=True))
        spawn(self.path, root=self.root)
        name = launch.call_args.kwargs["name"]
        self.assertLessEqual(len(name), 32)
        self.assertRegex(name, r"^[a-z0-9_-]+$")
        self.assertIn("abcdefghijkl", name)
        self.assertIn("he-999999", name)

    @patch("herdworks.hc.launch")
    def test_large_task_number_still_fits_core_session_name(self, launch):
        from herdworks.runs import read_task
        data = read_task(self.path)
        data.update(project="abcdefghijkl", id="HE-12345678901234567890")
        (self.path / "task.json").write_text(json.dumps(data))
        launch.return_value = dict(address="t2", first_message=dict(sent=True))
        spawn(self.path, root=self.root)
        name = launch.call_args.kwargs["name"]
        self.assertLessEqual(len(name), 32)
        self.assertRegex(name, r"^[a-z0-9_-]+$")
        self.assertIn("abcdefghijkl", name)
