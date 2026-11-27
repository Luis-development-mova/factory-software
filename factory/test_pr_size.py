import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).resolve().with_name("pr_size.py")


class PullRequestSizeTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Factory Test")
        self.git("commit", "-qm", "Base", "--allow-empty")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def commit(self):
        self.git("commit", "-qm", "Mudança")
        return self.git("rev-parse", "HEAD")

    def gate(self, *args, base=None):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--base", self.base if base is None else base, *args],
            cwd=self.repo, capture_output=True, text=True,
        )

    def test_staged_includes_docs_comments_and_blank_lines_in_the_limit(self):
        guide = self.repo / "guide.md"
        guide.write_text("linha antiga\n", encoding="utf-8")
        self.git("add", "guide.md")
        self.base = self.commit()
        guide.write_text("\n", encoding="utf-8")
        code = self.repo / "code.py"
        code.write_text("# comentário\n" * 298, encoding="utf-8")
        self.git("add", "guide.md", "code.py")
        guide.write_text("texto fora do index\n" * 500, encoding="utf-8")
        result = self.gate("--staged")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Adições 299 | exclusões 1 | total 300", result.stdout)

        code.write_text("# comentário\n" * 299, encoding="utf-8")
        self.git("add", "code.py")
        result = self.gate("--staged")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Adições 300 | exclusões 1 | total 301", result.stdout)
        self.assertIn("decomposição", result.stderr)
        committed = self.gate("--head", self.commit())
        self.assertEqual(committed.returncode, 1, committed.stderr)
        self.assertEqual(committed.stdout.splitlines()[-1], result.stdout.splitlines()[-1])

    def test_committed_head_excludes_changes_only_in_diverged_base(self):
        (self.repo / "feature.md").write_text("entrega\n", encoding="utf-8")
        self.git("add", "feature.md")
        head = self.commit()
        self.git("checkout", "-q", "--detach", self.base)
        (self.repo / "base.md").write_text("base\n" * 300, encoding="utf-8")
        self.git("add", "base.md")
        result = self.gate("--head", head, base=self.commit())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"ancestral {self.base}", result.stdout)
        self.assertIn("Adições 1 | exclusões 0 | total 1", result.stdout)

    def test_rename_counts_both_paths_even_with_rename_detection_configured(self):
        self.git("config", "diff.renames", "true")
        path = self.repo / "old\tname.md"
        path.write_text("documentação\n" * 151, encoding="utf-8")
        self.git("add", path.name)
        self.base = self.commit()
        self.git("mv", path.name, "new\nname.md")
        result = self.gate("--staged")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Adições 151 | exclusões 151 | total 302", result.stdout)

    def test_binary_blocks_with_or_without_forced_text_diff(self):
        (self.repo / "image.bin").write_bytes(b"\x00\xff")
        self.git("add", "image.bin")
        for attributes in (False, True):
            with self.subTest(attributes=attributes):
                if attributes:
                    (self.repo / ".gitattributes").write_text("*.bin diff\n", encoding="utf-8")
                    self.git("add", ".gitattributes")
                result = self.gate("--staged")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("binário", result.stderr)
                self.assertIn("decisão humana", result.stderr)

    def test_gitlink_has_no_line_count(self):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},module")
        result = self.gate("--staged")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("sem contagem de linhas", result.stderr)

    def test_invalid_reference_blocks(self):
        for base, head in ((self.base, "missing-reference"), (self.base, ""), ("", "HEAD")):
            with self.subTest(base=base, head=head):
                result = self.gate("--head", head, base=base)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Contagem inconclusiva", result.stderr)
