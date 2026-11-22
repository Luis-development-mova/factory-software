import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).with_name("build_approval.py")


class BuildApprovalTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.record_path = Path(directory.name) / "approval.json"
        self.base = "a" * 40
        self.diff = b"reviewed patch\n"
        self.record = {
            "decision": "APROVADO", "reviewer_session": "reviewer-session",
            "approver_session": "approver-session", "base_sha": self.base,
            "diff_sha256": hashlib.sha256(self.diff).hexdigest(),
        }

    def run_gate(self, diff=None, base=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.record_path), base or self.base],
            input=self.diff if diff is None else diff, capture_output=True,
        )

    def write_record(self, **changes):
        self.record_path.write_text(json.dumps({**self.record, **changes}), encoding="utf-8")

    def test_requires_an_approval_record(self):
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_allows_independent_approval_for_exact_base_and_diff(self):
        self.write_record()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_changed_version_or_invalid_approval(self):
        self.write_record()
        self.assertNotEqual(self.run_gate(diff=b"changed patch").returncode, 0)
        self.assertNotEqual(self.run_gate(base="b" * 40).returncode, 0)
        for changes in (
            {"decision": "VOLTAR"}, {"approver_session": ""},
            {"approver_session": self.record["reviewer_session"]},
        ):
            with self.subTest(changes=changes):
                self.write_record(**changes)
                self.assertNotEqual(self.run_gate().returncode, 0)
