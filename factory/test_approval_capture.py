import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import build_approval


SCRIPT = Path(__file__).with_name("approval_capture.py")
BASE, DIFF = "a" * 40, b"reviewed patch\n"


class ApprovalCaptureTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.jobs = self.root / "factory" / "jobs"
        self.jobs.mkdir(parents=True)
        (self.root / "evaluated.diff").write_bytes(DIFF)
        self.sha = hashlib.sha256(DIFF).hexdigest()
        self.context = {"base_sha": BASE, "diff_path": str(self.root / "evaluated.diff"), "diff_sha256": self.sha,
                        "builder_session": "builder-session", "reviewer_agent_type": "revisor-local",
                        "approver_agent_type": "aprovador-independente", "record_path": "factory/jobs/25-aprovacao.json"}
        (self.jobs / "aprovacao-em-curso.json").write_text(json.dumps(self.context), encoding="utf-8")
        self.record_path = self.root / self.context["record_path"]

    def verdict(self, **changes):
        return json.dumps({"decision": "APROVADO", "base_sha": BASE, "diff_sha256": self.sha, **changes})

    def approver(self, **changes):
        event = {"cwd": str(self.root), "session_id": "builder-session", "agent_id": "approver-agent",
                 "agent_type": "aprovador-independente", "last_assistant_message": self.verdict()}
        return {**event, **changes}

    def reviewer(self):
        return {"cwd": str(self.root), "session_id": "builder-session", "agent_id": "reviewer-agent",
                "agent_type": "revisor-local"}

    def handback(self, message, agent_id="approver-agent", session_id="builder-session", file_id=None):
        path = self.root / f"agent-{file_id or agent_id}.jsonl"
        entry = {"agentId": agent_id, "sessionId": session_id, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "SubagentHandback", "input": {"message": message}}]}}
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        return str(path)

    def run_hook(self, *events):
        for event in events:
            subprocess.run([sys.executable, "-I", str(SCRIPT)], input=json.dumps(event).encode(), capture_output=True, check=True)
        return json.loads(self.record_path.read_text(encoding="utf-8")) if self.record_path.exists() else None

    def log(self):
        return [json.loads(line) for line in (self.jobs / "aprovacao-eventos.jsonl").read_text(encoding="utf-8").splitlines()]

    def passes_gate(self, record):
        build_approval.check_approval(record, BASE, DIFF, BASE, self.log())

    def reset(self):
        self.record_path.unlink()
        (self.jobs / "aprovacao-eventos.jsonl").unlink()

    def test_without_context_nothing_is_recorded(self):
        (self.jobs / "aprovacao-em-curso.json").unlink()
        self.assertIsNone(self.run_hook(self.approver()))

    def test_text_delivery_links_id_base_and_diff_and_passes_gate(self):
        record = self.run_hook(self.reviewer(), self.approver())
        self.assertEqual((record["decision"], record["approver_session"], record["reasons"]), ("APROVADO", "approver-agent", []))
        self.passes_gate(record)

    def test_voltar_keeps_work_local(self):
        record = self.run_hook(self.reviewer(), self.approver(last_assistant_message=self.verdict(decision="VOLTAR")))
        self.assertEqual(record["decision"], "VOLTAR")
        with self.assertRaises(ValueError):
            self.passes_gate(record)

    def test_escalates_when_fields_or_link_are_missing_or_different(self):
        cases = {"sem agent_id": self.approver(agent_id=None), "sem decisão": self.approver(last_assistant_message="x"),
                 "SHA-256 diferente": self.approver(last_assistant_message=self.verdict(diff_sha256="b" * 64)),
                 "base diferente": self.approver(last_assistant_message=self.verdict(base_sha="c" * 40)),
                 "sessão diferente do Builder": self.approver(session_id="other-session")}
        for name, approver in cases.items():
            with self.subTest(name):
                record = self.run_hook(self.reviewer(), approver)
                self.assertEqual(record["decision"], "ESCALAR")
                with self.assertRaises(ValueError):
                    self.passes_gate(record)
                self.reset()

    def test_approver_before_reviewer_links_once_both_events_exist(self):
        self.assertIsNone(self.run_hook(self.approver()))
        self.assertEqual(self.run_hook(self.reviewer())["reviewer_session"], "reviewer-agent")

    def test_handback_delivery_links_id_session_base_and_diff(self):
        path = self.handback(self.verdict())
        record = self.run_hook(self.reviewer(), self.approver(last_assistant_message=None, agent_transcript_path=path))
        self.assertEqual((record["decision"], record["approver_session"], record["reasons"]), ("APROVADO", "approver-agent", []))
        self.passes_gate(record)

    def test_both_delivery_forms_agreeing_link_once(self):
        path = self.handback(self.verdict())
        record = self.run_hook(self.reviewer(), self.approver(agent_transcript_path=path))
        self.assertEqual(record["decision"], "APROVADO")
        self.assertEqual(self.log()[-1]["verdict_note"], "last_assistant_message+SubagentHandback.input.message")

    def test_divergent_delivery_forms_escalate(self):
        path = self.handback(self.verdict(diff_sha256="b" * 64))
        record = self.run_hook(self.reviewer(), self.approver(agent_transcript_path=path))
        self.assertEqual(record["decision"], "ESCALAR")
        self.assertTrue(any("fontes divergentes" in reason for reason in record["reasons"]))

    def test_handback_id_or_session_different_from_event_escalates(self):
        cases = {"agent_id": ({"agent_id": "other-agent"}, "agent_id ausente ou divergente"),
                 "session": ({"session_id": "other-session"}, "sessão de origem difere do Builder")}
        for name, (changes, reason) in cases.items():
            with self.subTest(name):
                path = self.handback(self.verdict(), file_id="approver-agent", **changes)
                record = self.run_hook(self.reviewer(), self.approver(last_assistant_message=None, agent_transcript_path=path))
                self.assertEqual(record["decision"], "ESCALAR")
                self.assertTrue(any(reason in r for r in record["reasons"]), record["reasons"])
                self.reset()


if __name__ == "__main__":
    unittest.main()
