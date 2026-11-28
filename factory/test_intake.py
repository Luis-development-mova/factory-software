import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import intake


class IntakeStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.jobs = Path(directory.name)
        self.job_path = self.jobs / "42.json"
        self.plan_path = self.jobs / "42-fase0.md"
        self.ticket = {"title": "Corrigir a página", "body": "Exibir um título"}
        self.issue = {"number": 42, **self.ticket}
        self.ready = {"status": "ready", "detail": "O título aparece na página"}
        self.blocked = {"status": "needs-human", "detail": "Qual título deve aparecer?"}
        self.patch_intake("JOBS", self.jobs)
        self.patch_intake("run_json", return_value=[[self.issue]])
        self.classify = self.patch_intake("classify", return_value=self.ready)
        self.plan = self.patch_intake("plan", return_value="Verificar título no HTML")

    def patch_intake(self, name, *args, **kwargs):
        patcher = patch.object(intake, name, *args, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def job(self):
        return json.loads(self.job_path.read_text(encoding="utf-8"))

    def refresh(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            intake.update()
        return output.getvalue()

    def test_writes_checkpoints_before_model_calls_and_regenerates_plan(self):
        def classify(ticket):
            self.assertEqual(self.job(), {"ticket": ticket, "state": "intake"})
            return self.ready

        def plan(ticket, criterion):
            self.assertEqual(self.job(), {"ticket": ticket, "state": "planning", "result": self.ready})
            return "Verificar título no HTML"

        self.classify.side_effect = classify
        self.plan.side_effect = plan
        self.assertIn("Issues prontas nesta execução: 42", self.refresh())
        self.assertEqual(self.job()["state"], "planned")
        self.plan_path.unlink()
        self.refresh()
        self.assertIn("Verificar título no HTML", self.plan_path.read_text(encoding="utf-8"))
        self.classify.assert_called_once_with(self.ticket)
        self.plan.assert_called_once_with(self.ticket, self.ready["detail"])

    def test_resumes_planning_after_failure_without_reclassifying(self):
        self.plan.side_effect = ValueError("planejamento interrompido")
        with self.assertRaisesRegex(ValueError, "planejamento interrompido"):
            self.refresh()
        self.assertEqual(self.job()["state"], "planning")
        self.assertEqual(self.job()["result"], self.ready)
        self.assertFalse(self.plan_path.exists())
        self.plan.side_effect = None
        self.assertIn("Issues prontas nesta execução: 42", self.refresh())
        self.assertEqual(self.job()["state"], "planned")
        self.classify.assert_called_once_with(self.ticket)
        self.assertEqual(self.plan.call_count, 2)

    def test_ambiguous_issue_waits_until_ticket_changes(self):
        self.classify.return_value = self.blocked
        for _ in range(2):
            self.assertIn("Issues prontas nesta execução: nenhuma", self.refresh())
            self.assertEqual(self.job()["state"], "blocked")
        self.classify.assert_called_once_with(self.ticket)
        self.plan.assert_not_called()

        self.issue["body"] = "Exibir título Olá, fábrica!"
        self.classify.return_value = self.ready
        self.assertIn("Issues prontas nesta execução: 42", self.refresh())
        self.assertEqual(self.job()["ticket"]["body"], self.issue["body"])
        self.assertEqual(self.job()["state"], "planned")
        self.assertEqual(self.classify.call_count, 2)
        self.plan.assert_called_once()

    def test_migrates_legacy_planned_job_and_keeps_acceptance_visible(self):
        self.job_path.write_text(json.dumps({"ticket": self.ticket, "result": self.ready,
                                             "plan": "Plano da versão anterior"}), encoding="utf-8")
        (self.jobs / "42-aceite.json").write_text(json.dumps({"ticket": self.ticket,
                                                             "message": "Aceite passou"}), encoding="utf-8")
        self.refresh()
        self.assertEqual(self.job()["state"], "planned")
        self.assertEqual(self.job()["ticket"], self.ticket)
        self.assertIn("Plano da versão anterior", self.plan_path.read_text(encoding="utf-8"))
        self.assertIn("Aceite passou", (self.jobs / "index.html").read_text(encoding="utf-8"))
        self.classify.assert_not_called()
        self.plan.assert_not_called()

    def test_resumes_legacy_job_with_classification_only(self):
        self.job_path.write_text(json.dumps({"ticket": self.ticket, "result": self.ready}), encoding="utf-8")
        self.refresh()
        self.assertEqual(self.job()["state"], "planned")
        self.classify.assert_not_called()
        self.plan.assert_called_once_with(self.ticket, self.ready["detail"])

    def test_cannot_skip_planning(self):
        job = {"ticket": self.ticket, "state": "intake"}
        with self.assertRaisesRegex(ValueError, "Transição inválida"):
            intake.transition(self.job_path, job, "planned", result=self.ready, plan="Plano válido")
        self.assertFalse(self.job_path.exists())

    def test_rejects_checkpoint_without_required_plan(self):
        invalid = json.dumps({"ticket": self.ticket, "result": self.ready, "state": "planned"})
        self.job_path.write_text(invalid, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "issue #42.*Estado do job"):
            self.refresh()
        self.assertEqual(self.job_path.read_text(encoding="utf-8"), invalid)
        self.assertFalse(self.plan_path.exists())
        self.classify.assert_not_called()
        self.plan.assert_not_called()
