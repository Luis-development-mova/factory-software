import json
import subprocess
import sys
import unittest
from pathlib import Path

from review_filter import filter_findings

FILTER = Path(__file__).with_name("review_filter.py")
VALIDATORS = ["V1", "V2"]


def vote(validator="V1", confirmed=True, reason="evidência lida no SHA"):
    return {"validator": validator, "confirmed": confirmed, "reason": reason}


def finding(fid, revisor="R1", label="nitpick", **changes):
    data = {
        "id": fid,
        "file": "a.md",
        "line": 3,
        "scenario": "cenário",
        "evidence": "evidência",
        "impact": "impacto",
        "label": label,
        "revisor": revisor,
        "votes": [vote("V1"), vote("V2")],
    }
    data.update(changes)
    return data


def ids(items):
    return [item["id"] for item in items]


def internos_ids(result):
    return [item["achado"]["id"] for item in result["internos"]]


class ValidatorsTest(unittest.TestCase):
    def test_string_is_rejected_even_with_two_characters(self):
        with self.assertRaises(ValueError):
            filter_findings("ab", [])

    def test_single_validator_is_rejected(self):
        with self.assertRaises(ValueError):
            filter_findings(["V1"], [])

    def test_duplicate_validators_are_rejected(self):
        with self.assertRaises(ValueError):
            filter_findings(["V1", "V1"], [])

    def test_non_text_validator_is_rejected(self):
        with self.assertRaises(ValueError):
            filter_findings(["V1", 2], [])

    def test_blank_validator_is_rejected(self):
        with self.assertRaises(ValueError):
            filter_findings(["V1", "  "], [])

    def test_findings_must_be_a_list(self):
        with self.assertRaises(ValueError):
            filter_findings(VALIDATORS, None)


class FindingsTest(unittest.TestCase):
    def test_unanimous_finding_is_publishable_without_votes_field(self):
        result = filter_findings(VALIDATORS, [finding("F1")])
        self.assertEqual(ids(result["publicaveis"]), ["F1"])
        self.assertNotIn("votes", result["publicaveis"][0])

    def test_malformed_finding_does_not_stop_valid_ones(self):
        result = filter_findings(VALIDATORS, [finding("F1"), finding("F2", file=None), finding("F3")])
        self.assertEqual(ids(result["publicaveis"]), ["F1", "F3"])
        self.assertEqual(result["internos"][0]["motivo"], "campo ausente ou vazio: file")

    def test_non_object_finding_goes_to_internos(self):
        result = filter_findings(VALIDATORS, ["não é objeto", finding("F1")])
        self.assertEqual(ids(result["publicaveis"]), ["F1"])
        self.assertEqual(result["internos"][0]["motivo"], "achado não é um objeto")

    def test_vote_without_validator_key_goes_to_internos(self):
        broken = finding("F2", votes=[{"confirmed": True, "reason": "x"}, vote("V2")])
        result = filter_findings(VALIDATORS, [finding("F1"), broken, finding("F3")])
        self.assertEqual(ids(result["publicaveis"]), ["F1", "F3"])
        self.assertEqual(result["internos"][0]["motivo"], "voto malformado")

    def test_missing_revisor_goes_to_internos(self):
        result = filter_findings(VALIDATORS, [finding("F1", revisor=None)])
        self.assertEqual(result["internos"][0]["motivo"], "campo ausente ou vazio: revisor")

    def test_line_must_be_positive_integer(self):
        bad_lines = [True, 0, "3", 2.5]
        findings = [finding(f"F{i}", line=line) for i, line in enumerate(bad_lines)]
        result = filter_findings(VALIDATORS, findings)
        self.assertEqual(ids(result["publicaveis"]), [])
        self.assertEqual(len(result["internos"]), len(bad_lines))
        self.assertTrue(all(item["motivo"] == "linha inválida" for item in result["internos"]))

    def test_label_outside_list_goes_to_internos(self):
        result = filter_findings(VALIDATORS, [finding("F1", label="crítico")])
        self.assertEqual(result["internos"][0]["motivo"], "rótulo fora da lista")

    def test_missing_validator_vote_goes_to_internos(self):
        result = filter_findings(VALIDATORS, [finding("F1", votes=[vote("V1")])])
        self.assertEqual(result["internos"][0]["motivo"], "votos ausentes, duplicados ou fora do grupo")

    def test_vote_from_outside_group_goes_to_internos(self):
        result = filter_findings(VALIDATORS, [finding("F1", votes=[vote("V1"), vote("V9")])])
        self.assertEqual(result["internos"][0]["motivo"], "votos ausentes, duplicados ou fora do grupo")

    def test_rejected_vote_goes_to_internos(self):
        result = filter_findings(VALIDATORS, [finding("F1", votes=[vote("V1"), vote("V2", confirmed=False)])])
        self.assertEqual(result["internos"][0]["motivo"], "sem unanimidade fundamentada")


class NitpickLimitTest(unittest.TestCase):
    def test_fourth_nitpick_of_same_reviewer_goes_to_internos(self):
        findings = [finding(f"F{i}", revisor="R1") for i in range(1, 5)]
        result = filter_findings(VALIDATORS, findings)
        self.assertEqual(ids(result["publicaveis"]), ["F1", "F2", "F3"])
        self.assertEqual(internos_ids(result), ["F4"])
        self.assertEqual(result["internos"][0]["motivo"], "limite de três nitpicks por revisor excedido")

    def test_limit_is_counted_per_reviewer(self):
        findings = [finding(f"A{i}", revisor="R1") for i in range(3)] + [finding(f"B{i}", revisor="R2") for i in range(3)]
        result = filter_findings(VALIDATORS, findings)
        self.assertEqual(len(result["publicaveis"]), 6)
        self.assertEqual(result["internos"], [])

    def test_importante_does_not_count_toward_limit(self):
        findings = [finding(f"F{i}", revisor="R1", label="importante") for i in range(4)]
        result = filter_findings(VALIDATORS, findings)
        self.assertEqual(len(result["publicaveis"]), 4)

    def test_rejected_nitpick_does_not_consume_limit(self):
        findings = [finding("F0", revisor="R1", votes=[vote("V1", confirmed=False), vote("V2")])]
        findings += [finding(f"F{i}", revisor="R1") for i in range(1, 4)]
        result = filter_findings(VALIDATORS, findings)
        self.assertEqual(ids(result["publicaveis"]), ["F1", "F2", "F3"])
        self.assertEqual(internos_ids(result), ["F0"])


class CommandLineTest(unittest.TestCase):
    def run_filter(self, payload):
        return subprocess.run(
            [sys.executable, "-I", str(FILTER)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def test_valid_input_exits_zero_and_prints_both_lists(self):
        completed = self.run_filter({"validators": VALIDATORS, "findings": [finding("F1"), finding("F2", file=None)]})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(ids(output["publicaveis"]), ["F1"])
        self.assertEqual(internos_ids(output), ["F2"])

    def test_invalid_group_exits_one_with_message(self):
        completed = self.run_filter({"validators": ["V1"], "findings": []})
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Entrada inválida", completed.stderr)


if __name__ == "__main__":
    unittest.main()
