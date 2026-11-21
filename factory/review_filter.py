import json
import sys
from collections import Counter


def filter_findings(validators, findings):
    if len(validators) < 2 or len(set(validators)) != len(validators):
        raise ValueError("Informe pelo menos dois validadores distintos.")
    expected = Counter(validators)
    result = {"publicaveis": [], "internos": []}
    for finding in findings:
        votes = finding.get("votes", [])
        complete = Counter(vote["validator"] for vote in votes) == expected
        unanimous = complete and all(
            vote.get("confirmed") is True and vote.get("reason", "").strip()
            for vote in votes
        )
        evidence = (
            all(finding.get(key, "").strip() for key in ("file", "scenario", "evidence", "impact"))
            and type(finding.get("line")) is int
            and finding["line"] > 0
            and finding.get("label") in {"importante", "nitpick", "já existente"}
        )
        if unanimous and evidence:
            result["publicaveis"].append({key: value for key, value in finding.items() if key != "votes"})
        else:
            reason = (
                "votos ausentes, duplicados ou fora do grupo" if not complete
                else "sem unanimidade fundamentada" if not unanimous
                else "achado sem referência ou evidência suficiente"
            )
            result["internos"].append({"achado": finding, "motivo": reason})
    return result


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        print(json.dumps(filter_findings(data["validators"], data["findings"]), ensure_ascii=False, indent=2))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        sys.exit(f"Entrada inválida para o filtro de revisão: {error}")
