import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).with_name("build_approval.py")
IDENTITY = ["-c", "user.name=teste", "-c", "user.email=teste@example.com"]


def git(*args, cwd):
    return subprocess.run(["git", *IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class BuildApprovalTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.remote, self.work = root / "remote.git", root / "work"
        git("init", "-q", "--bare", str(self.remote), cwd=root)
        git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.remote)
        git("init", "-q", str(self.work), cwd=root)
        git("remote", "add", "origin", str(self.remote), cwd=self.work)
        self.publish("primeiro")
        self.base = git("rev-parse", "HEAD", cwd=self.work)
        self.record_path, self.log_path = root / "approval.json", root / "aprovacao-eventos.jsonl"
        self.diff = b"reviewed patch\n"
        self.record = {
            "decision": "APROVADO", "origin": "claude-code-hook", "approval_event": "SubagentStop",
            "builder_session": "builder-session", "reviewer_session": "reviewer-session",
            "approver_session": "approver-session", "base_sha": self.base,
            "diff_sha256": hashlib.sha256(self.diff).hexdigest(),
        }

    def publish(self, message):
        git("commit", "-q", "--allow-empty", "-m", message, cwd=self.work)
        git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=self.work)

    def run_gate(self, diff=None, base=None):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.record_path), base or self.base],
                              input=self.diff if diff is None else diff, capture_output=True, cwd=self.work)

    def write_record(self, **changes):
        self.record_path.write_text(json.dumps({**self.record, **changes}), encoding="utf-8")

    def write_matching_log(self, **changes):
        verdict = {"decision": "APROVADO", "base_sha": self.base, "diff_sha256": self.record["diff_sha256"], **changes}
        events = [{"agent_id": self.record["reviewer_session"], "agent_type": "revisor-local"},
                  {"agent_id": self.record["approver_session"], "agent_type": "aprovador-independente", "verdict": verdict}]
        self.log_path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    def test_requires_an_approval_record(self):
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_allows_independent_approval_for_exact_base_and_diff(self):
        self.write_record()
        self.write_matching_log()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_record_without_matching_event_log(self):
        # Prova que um registro gravado à mão, sem evento correspondente, é recusado.
        self.write_record()
        self.assertNotEqual(self.run_gate().returncode, 0)
        self.write_matching_log(diff_sha256="d" * 64)
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_rejects_changed_diff_or_base_informed_by_executor(self):
        self.write_record()
        self.write_matching_log()
        self.assertNotEqual(self.run_gate(diff=b"changed patch").returncode, 0)
        self.assertNotEqual(self.run_gate(base="b" * 40).returncode, 0)

    def test_rejects_base_moved_on_remote_even_when_executor_informs_old_base(self):
        # Prova que o gate consulta o remoto: a base informada e a do registro são as antigas.
        self.write_record()
        self.write_matching_log()
        self.publish("segundo")
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"base remota atual difere", result.stdout + result.stderr)

    def test_rejects_approval_without_verifiable_origin(self):
        # Prova só a forma do registro: origem ausente, de outro tipo ou de evento diferente de SubagentStop é recusada.
        for changes in ({"origin": None}, {"origin": "orquestrador"}, {"approval_event": "manual"}):
            with self.subTest(changes=changes):
                self.write_record(**changes)
                self.write_matching_log()
                result = self.run_gate()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("origem verificável", (result.stdout + result.stderr).decode())

    def test_rejects_invalid_or_shared_sessions(self):
        for changes in (
            {"decision": "VOLTAR"}, {"approver_session": ""}, {"builder_session": None},
            {"approver_session": self.record["reviewer_session"]},
            {"approver_session": self.record["builder_session"]},
            {"approver_session": " Builder-Session "}, {"reviewer_session": self.record["builder_session"]},
        ):
            with self.subTest(changes=changes):
                self.write_record(**changes)
                self.write_matching_log()
                self.assertNotEqual(self.run_gate().returncode, 0)


if __name__ == "__main__":
    unittest.main()
