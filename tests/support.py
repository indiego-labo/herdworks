import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import json
from unittest.mock import patch
from herdworks.runs import git, append_event
from herdworks.projects import add_project, new_task


class RunCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Fixture")
        (self.repo / "hello.py").write_text("print('hello')\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "test: baseline")
        self.brief = self.root / "request.md"
        self.brief.write_text("ORIGINAL REQUEST")
        self.home = self.root / "home"
        self.environment = patch.dict(os.environ, HW_HOME=str(self.home))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # Token counts come from the agents' own databases; tests never read the real ones.
        for reader in ("opencode_db", "codex_db"):
            source = patch(f"herdworks.tokens.{reader}", return_value=self.root / f"no-{reader}")
            source.start()
            self.addCleanup(source.stop)
        self.project = add_project("unit", self.repo, prefix="HE")
        self.path, _ = new_task(self.project, self.brief)
        self.notes = self.project / "coordinator/tasks/HE-1"
        (self.project / "coordinator.json").write_text(json.dumps(dict(name="hw-unit-coord", address="t1")))

    def commit(self, timestamp=None):
        (self.repo / "hello.py").write_text("print('changed')\n")
        git(self.repo, "add", ".")
        env = dict(os.environ)
        if timestamp:
            env.update(GIT_AUTHOR_DATE=f"@{timestamp} +0000", GIT_COMMITTER_DATE=f"@{timestamp} +0000")
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "test: change"],
                       env=env, capture_output=True, check=True)
        return git(self.repo, "rev-parse", "HEAD")


def write_claims(folder, *grades):
    """Save claims.json beside a verdict: one claim per grade, each backed by a saved evidence file."""
    (folder / 'evidence').mkdir(exist_ok=True)
    claims = []
    for number, grade in enumerate(grades or ('PROVED',), 1):
        claim = dict(id=f'AC-{number}', grade=grade)
        if grade == 'NOT_PROVED':
            claim['reason'] = 'needs a device this machine lacks'
        else:
            (folder / f'evidence/ac{number}.txt').write_text('python3 hello.py Ada\nHello, Ada!\n')
            claim.update(check='python3 hello.py Ada', evidence=f'../evidence/ac{number}.txt')
        claims.append(claim)
    (folder / 'claims.json').write_text(json.dumps(claims))


class GateCase(RunCase):
    def setUp(self):
        super().setUp()
        git(self.repo, 'checkout', '-b', 'hw/HE-1')
        self.sha = self.commit()
        self.build = self.path / 'build-1'
        self.verify = self.path / 'verify-1'
        self.review = self.path / 'evidence-1'
        for folder in (self.build, self.verify, self.review):
            folder.mkdir()
        now = time.time()
        self.report = self.build / 'report.md'
        self.report.write_text(f'READY {self.sha}\n')
        os.utime(self.report, (now - 4, now - 4))
        self.verdict = self.verify / 'verdict.md'
        self.verdict.write_text(f'PASS\nCommit: {self.sha}\n')
        os.utime(self.verdict, (now - 2, now - 2))
        (self.verify / 'evidence').mkdir()
        (self.verify / 'evidence/cli.txt').write_text('python3 hello.py Ada\nHello, Ada!\n')
        write_claims(self.verify)
        (self.review / 'review.md').write_text('CONFIRMED\n')
        for role, address, start, metadata in [
                ('build', 't2', now - 5, {}),
                ('verify', 't3', now - 3, {'commit': self.sha}),
                ('evidence', 't4', now - 1, {'commit': self.sha, 'verifier': 'hw-unit-he-1-verify-1'})]:
            append_event(self.path, dict(event='session', role=role, address=address,
                                         name=f'hw-unit-he-1-{role}-1', folder=f'{role}-1',
                                         started_at=start, stuck_after_minutes=60,
                                         launch_source='template', **metadata))
