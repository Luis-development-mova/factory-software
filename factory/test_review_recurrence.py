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
                     scenario="Link quebrado", confirmed=True, cause_confirmed=True,
                     pattern="link-markdown-quebrado", with_cause=True):
        finding = {
            "id": "F1", "file": f"guia-{number}.md", "line": 3,
            "scenario": scenario, "evidence": "O alvo não existe.", "impact": "Link indisponível.",
            "label": "nitpick", "revisor": "R1", "pattern": pattern,
            "cause": {"file": source, "line": 3, "fragment": fragment,
                      "evidence": "O manifesto aponta para esse trecho do modelo.",
                      "proposal": "Corrigir o alvo no modelo e regenerar os guias."} if with_cause else None,
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

    def test_unanimous_cause_above_nitpick_limit_still_proposes_fix(self):
        self.write_review(8)
        path = self.jobs / "pr-8-votos.json"
        review = json.loads(path.read_text())
        original, = review["findings"]
        extras = [dict(original, id=f"N{i}", pattern=f"outro sintoma {i}", cause=None) for i in range(3)]
        review["findings"] = extras + [original]
        path.write_text(json.dumps(review))
        self.write_review(10)
        result = detect_recurrence(self.jobs, "owner/repo", 10)
        proposal, = result["propostas"]
        self.assertEqual([item["pr"] for item in proposal["ocorrencias"]], [8, 10])

    def test_pattern_spacing_and_hyphens_count_as_same_symptom(self):
        self.write_review(8, pattern="link-markdown-quebrado", with_cause=False)
        self.write_review(9, pattern="imagem ausente", with_cause=False)
        self.write_review(10, pattern="link markdown quebrado", with_cause=False)
        result = detect_recurrence(self.jobs, "owner/repo", 10)
        suspicion, = result["suspeitas"]
        self.assertEqual(suspicion["padrao"], "link markdown quebrado")
        self.assertEqual([item["pr"] for item in suspicion["ocorrencias"]], [8, 10])

    def test_history_file_without_repo_registers_gap_and_is_skipped(self):
        self.write_review(8)
        history = self.jobs / "pr-8-votos.json"
        review = json.loads(history.read_text())
        del review["repo"]
        history.write_text(json.dumps(review))
        self.write_review(10)
        result = detect_recurrence(self.jobs, "owner/repo", 10)
        self.assertEqual(result["propostas"], [])
        self.assertEqual(result["lacunas"], [
            {"arquivo": "pr-8-votos.json", "motivo": "O registro não informa o repositório."},
        ])
