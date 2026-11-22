import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import build_approval


SCRIPT = Path(__file__).with_name("approval_capture.py")
BASE = "a" * 40
DIFF = b"reviewed patch\n"


class ApprovalCaptureTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.jobs = self.root / "factory" / "jobs"
        self.jobs.mkdir(parents=True)
        (self.root / "evaluated.diff").write_bytes(DIFF)
        self.context = {
            "base_sha": BASE, "diff_path": str(self.root / "evaluated.diff"),
            "diff_sha256": hashlib.sha256(DIFF).hexdigest(), "builder_session": "builder-session",
            "reviewer_agent_type": "revisor-local", "approver_agent_type": "aprovador-independente",
            "record_path": "factory/jobs/25-aprovacao.json",
        }
        self.write_context()
        self.record_path = self.root / self.context["record_path"]

    def write_context(self):
        (self.jobs / "aprovacao-em-curso.json").write_text(json.dumps(self.context), encoding="utf-8")

    def event(self, **changes):
        payload = {
            "cwd": str(self.root), "session_id": "builder-session", "agent_id": "approver-agent",
            "agent_type": "aprovador-independente",
            "last_assistant_message": json.dumps({
                "decision": "APROVADO", "base_sha": BASE,
                "diff_sha256": self.context["diff_sha256"], "reason": "ok",
            }),
        }
        return {**payload, **changes}

    def reviewer_event(self):
        return {"cwd": str(self.root), "session_id": "builder-session",
                "agent_id": "reviewer-agent", "agent_type": "revisor-local"}

    def run_hook(self, *events):
        for event in events:
            subprocess.run([sys.executable, "-I", str(SCRIPT)], input=json.dumps(event).encode(),
                           capture_output=True, check=True)
        return json.loads(self.record_path.read_text(encoding="utf-8")) if self.record_path.exists() else None

    def test_without_context_nothing_is_recorded(self):
        (self.jobs / "aprovacao-em-curso.json").unlink()
        self.assertIsNone(self.run_hook(self.event()))

    def test_approved_event_links_agent_id_base_and_diff_and_passes_gate(self):
        record = self.run_hook(self.reviewer_event(), self.event())
        self.assertEqual(record["decision"], "APROVADO")
        self.assertEqual(record["approver_session"], "approver-agent")
        self.assertEqual(record["reviewer_session"], "reviewer-agent")
        self.assertEqual(record["reasons"], [])
        build_approval.check_approval(record, BASE, DIFF, BASE)

    def test_voltar_keeps_work_local(self):
        verdict = json.dumps({"decision": "VOLTAR", "base_sha": BASE,
                              "diff_sha256": self.context["diff_sha256"]})
        record = self.run_hook(self.reviewer_event(), self.event(last_assistant_message=verdict))
        self.assertEqual(record["decision"], "VOLTAR")
        with self.assertRaises(ValueError):
            build_approval.check_approval(record, BASE, DIFF, BASE)

    def test_escalates_when_event_fields_or_link_are_missing_or_different(self):
        cases = {
            "sem agent_id": self.event(agent_id=None),
            "sem decisão": self.event(last_assistant_message="sem json"),
            "SHA-256 diferente": self.event(last_assistant_message=json.dumps(
                {"decision": "APROVADO", "base_sha": BASE, "diff_sha256": "b" * 64})),
            "base diferente": self.event(last_assistant_message=json.dumps(
                {"decision": "APROVADO", "base_sha": "c" * 40, "diff_sha256": self.context["diff_sha256"]})),
            "sessão diferente do Builder": self.event(session_id="other-session"),
        }
        for name, approver in cases.items():
            with self.subTest(name):
                record = self.run_hook(self.reviewer_event(), approver)
                self.assertEqual(record["decision"], "ESCALAR")
                self.assertTrue(record["reasons"])
                with self.assertRaises(ValueError):
                    build_approval.check_approval(record, BASE, DIFF, BASE)
                self.record_path.unlink()

    def test_approver_before_reviewer_still_links_once_both_events_exist(self):
        self.assertIsNone(self.run_hook(self.event()))
        record = self.run_hook(self.reviewer_event())
        self.assertEqual(record["decision"], "APROVADO")
        self.assertEqual(record["reviewer_session"], "reviewer-agent")


if __name__ == "__main__":
    unittest.main()
