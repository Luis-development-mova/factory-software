import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from review_recurrence import detect_recurrence


class ReviewRecurrenceTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.jobs = Path(directory.name)

    def write_review(self, number, *, source="modelos/guia.tpl", fragment="errado.md",
                     scenario="Link quebrado", confirmed=True, cause_confirmed=True):
        finding = {
            "id": "F1", "file": f"guia-{number}.md", "line": 3,
            "scenario": scenario, "evidence": "O alvo não existe.", "impact": "Link indisponível.",
            "label": "nitpick", "revisor": "R1", "pattern": "link-markdown-quebrado",
            "cause": {"file": source, "line": 3, "fragment": fragment,
                      "evidence": "O manifesto aponta para esse trecho do modelo.",
                      "proposal": "Corrigir o alvo no modelo e regenerar os guias."},
            "votes": [
                {"validator": voter, "confirmed": confirmed, "reason": "Revisei o achado.",
                 "cause_confirmed": cause_confirmed}
                for voter in ("V1", "V2")
            ],
        }
        review = {"repo": "owner/repo", "head_sha": "a" * 40,
                  "validators": ["V1", "V2"], "findings": [finding]}
        (self.jobs / f"pr-{number}-votos.json").write_text(json.dumps(review))

    def test_same_confirmed_cause_proposes_one_fix_across_prs(self):
        self.write_review(8, scenario="Leia o manual")
        self.write_review(10, scenario="Consulte a documentação")
        result = detect_recurrence(self.jobs, "owner/repo", 10)
        proposal, = result["propostas"]
        self.assertEqual(proposal["origem"]["file"], "modelos/guia.tpl")
        self.assertEqual([item["pr"] for item in proposal["ocorrencias"]], [8, 10])

    def test_same_symptom_does_not_prove_cause(self):
        self.write_review(8, source="modelos/outro.tpl")
        self.write_review(9, fragment="outro-alvo.md")
        self.write_review(10)
        result = detect_recurrence(self.jobs, "owner/repo", 10)
        self.assertEqual(result["propostas"], [])
        self.assertEqual(result["suspeitas"], [])

    def test_only_unanimous_findings_and_cause_votes_count(self):
        self.write_review(8, cause_confirmed=False)
        self.write_review(9, confirmed=False)
        self.write_review(10)
        result = detect_recurrence(self.jobs, "owner/repo", 10)
        self.assertEqual(result["propostas"], [])
        suspicion, = result["suspeitas"]
        self.assertEqual([item["pr"] for item in suspicion["ocorrencias"]], [8, 10])
