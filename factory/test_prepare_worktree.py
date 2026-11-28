import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).with_name("prepare_worktree.py")


class PrepareWorktreeTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name).resolve() / "consumer repo"
        self.repo.mkdir()
        self.git(self.repo, "init", "--quiet")
        (self.repo / "tracked.txt").write_text("base\n")
        (self.repo / ".gitignore").write_text("/factory/jobs/\n")
        self.git(self.repo, "add", "tracked.txt", ".gitignore")
        self.commit()
        self.base = self.git(self.repo, "rev-parse", "HEAD")
        self.checkout = self.repo.with_name("consumer repo.factory-worktrees") / "issue-12"

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    def commit(self, *args):
        self.git(self.repo, "-c", "user.name=Factory", "-c", "user.email=factory@example.test",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Fixture", *args)

    def prepare(self, repo=None, base=None, issue="12"):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--repo", str(repo or self.repo),
             "--issue", issue, "--base", base or self.base],
            capture_output=True, text=True, timeout=15,
        )

    def assert_prepared(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), self.checkout)

    def test_prepares_exact_base_and_reuses_from_another_worktree(self):
        tracked = self.repo / "tracked.txt"
        tracked.write_text("local change\n")
        self.assert_prepared(self.prepare())
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.base)
        self.assertEqual(self.git(self.checkout, "branch", "--show-current"), "")
        self.assertEqual((self.checkout / "tracked.txt").read_text(), "base\n")
        self.assertEqual(tracked.read_text(), "local change\n")

        jobs = self.checkout / "factory" / "jobs"
        jobs.mkdir(parents=True)
        checkpoint = jobs / "12.json"
        checkpoint.write_text('{"state":"planning"}')
        self.assert_prepared(self.prepare(repo=self.checkout, issue="012"))
        self.assertEqual(checkpoint.read_text(), '{"state":"planning"}')
        self.assertEqual(self.git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 2)

    def test_concurrent_preparation_reuses_one_checkout(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.prepare)
            second = pool.submit(self.prepare)
            self.assert_prepared(first.result())
            self.assert_prepared(second.result())
        self.assertEqual(self.git(self.repo, "worktree", "list", "--porcelain").count("worktree "), 2)

    def test_preserves_pending_work(self):
        self.assert_prepared(self.prepare())
        new_file = self.checkout / "pending.txt"
        new_file.write_text("unsaved work\n")
        for mode in ("untracked", "staged"):
            with self.subTest(mode=mode):
                result = self.prepare()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("alterações pendentes", result.stderr)
                self.assertEqual(new_file.read_text(), "unsaved work\n")
            if mode == "untracked":
                self.git(self.checkout, "add", "pending.txt")
        self.assertIn("A  pending.txt", self.git(self.checkout, "status", "--short"))

    def test_preserves_worktree_when_base_changes(self):
        self.assert_prepared(self.prepare())
        self.commit("--allow-empty")
        updated = self.git(self.repo, "rev-parse", "HEAD")
        result = self.prepare(base=updated)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA da base", result.stderr)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.base)

    def test_rejects_unregistered_directory(self):
        self.checkout.mkdir(parents=True)
        sentinel = self.checkout / "existing.txt"
        sentinel.write_text("keep\n")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("já existe", result.stderr)
        self.assertEqual(sentinel.read_text(), "keep\n")

    def test_rejects_a_worktree_attached_to_a_branch(self):
        self.assert_prepared(self.prepare())
        self.git(self.checkout, "switch", "--quiet", "-c", "local-work")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("precisa estar destacada", result.stderr)
        self.assertEqual(self.git(self.checkout, "branch", "--show-current"), "local-work")

    def test_rejects_a_link_at_the_reserved_path(self):
        self.checkout.parent.mkdir()
        self.checkout.symlink_to(self.repo, target_is_directory=True)
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("link simbólico", result.stderr)
        self.assertEqual(self.checkout.readlink(), self.repo)

    def test_rejects_invalid_issue_or_symbolic_base(self):
        for inputs in ({"issue": "../12"}, {"issue": "0"}, {"base": "HEAD"}):
            with self.subTest(inputs=inputs):
                result = self.prepare(**inputs)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("--" + next(iter(inputs)) + " precisa", result.stderr)
                self.assertFalse(self.checkout.parent.exists())


if __name__ == "__main__":
    unittest.main()
