import json
import sys
from collections import Counter

LABELS = {"importante", "nitpick", "já existente"}
NITPICK_LIMIT = 3
TEXT_FIELDS = ("file", "scenario", "evidence", "impact", "revisor")


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def check_validators(validators):
    if not isinstance(validators, list) or len(validators) < 2:
        raise ValueError("validators deve ser uma lista com pelo menos dois IDs.")
    if not all(_is_text(validator) for validator in validators):
        raise ValueError("validators deve conter apenas IDs de texto não vazios.")
    if len(set(validators)) != len(validators):
        raise ValueError("validators deve conter IDs distintos.")


def _malformed_reason(finding):
    if not isinstance(finding, dict):
        return "achado não é um objeto"
    for key in TEXT_FIELDS:
        if not _is_text(finding.get(key)):
            return f"campo ausente ou vazio: {key}"
    line = finding.get("line")
    if type(line) is not int or line <= 0:
        return "linha inválida"
    if finding.get("label") not in LABELS:
        return "rótulo fora da lista"
    votes = finding.get("votes")
    if not isinstance(votes, list):
        return "votos ausentes ou inválidos"
    for vote in votes:
        if not isinstance(vote, dict) or not _is_text(vote.get("validator")):
            return "voto malformado"
        if type(vote.get("confirmed")) is not bool or not _is_text(vote.get("reason")):
            return "voto malformado"
    return None


def _publication_reason(finding, expected):
    malformed = _malformed_reason(finding)
    if malformed:
        return malformed
    if Counter(vote["validator"] for vote in finding["votes"]) != expected:
        return "votos ausentes, duplicados ou fora do grupo"
    if not all(vote["confirmed"] is True for vote in finding["votes"]):
        return "sem unanimidade fundamentada"
    return None


def filter_findings(validators, findings):
    check_validators(validators)
    if not isinstance(findings, list):
        raise ValueError("findings deve ser uma lista.")
    expected = Counter(validators)
    nitpicks_by_reviewer = Counter()
    result = {"publicaveis": [], "internos": []}
    for finding in findings:
        reason = _publication_reason(finding, expected)
        if reason is None and finding["label"] == "nitpick":
            if nitpicks_by_reviewer[finding["revisor"]] >= NITPICK_LIMIT:
                reason = "limite de três nitpicks por revisor excedido"
            else:
                nitpicks_by_reviewer[finding["revisor"]] += 1
        if reason is None:
            result["publicaveis"].append({key: value for key, value in finding.items() if key != "votes"})
        else:
            result["internos"].append({"achado": finding, "motivo": reason})
    return result


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError("a entrada deve ser um objeto JSON.")
        print(json.dumps(filter_findings(data.get("validators"), data.get("findings")), ensure_ascii=False, indent=2))
    except ValueError as error:
        sys.exit(f"Entrada inválida para o filtro de revisão: {error}")
