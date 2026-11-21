import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys

from review_filter import filter_findings


def confirmed_cause(finding):
    cause = finding.get("cause")
    if not isinstance(cause, dict):
        return None
    line = cause.get("line")
    if type(line) is not int or line < 1:
        return None
    fields = ("file", "fragment", "evidence", "proposal")
    if not all(isinstance(cause.get(key), str) and cause[key].strip() for key in fields):
        return None
    votes = finding.get("votes")
    if not isinstance(votes, list) or not all(
        isinstance(vote, dict) and vote.get("cause_confirmed") is True for vote in votes
    ):
        return None
    return {key: cause[key].strip() for key in fields} | {"line": line}


def normalize_pattern(pattern):
    return re.sub(r"[\s_-]+", " ", pattern.strip().lower()).strip()


def unanimous_findings(review):
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings deve ser uma lista.")
    candidates = [
        {**finding, "cause": confirmed_cause(finding)} if isinstance(finding, dict) else finding
        for finding in findings
    ]
    return filter_findings(review.get("validators"), candidates)["publicaveis"]


def detect_recurrence(jobs, repo, current_pr):
    result = {"propostas": [], "suspeitas": [], "lacunas": []}
    by_cause = defaultdict(list)
    by_pattern = defaultdict(list)
    current = jobs / f"pr-{current_pr}-votos.json"
    for path in sorted(set(jobs.glob("pr-*-votos.json")) | {current}):
        match = re.fullmatch(r"pr-([1-9][0-9]*)-votos\.json", path.name)
        if not match:
            continue
        number = int(match[1])
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(review, dict):
                raise ValueError("O registro deve ser um objeto JSON.")
            if not isinstance(review.get("repo"), str) or not review["repo"].strip():
                raise ValueError("O registro não informa o repositório.")
            if review["repo"].lower() != repo.lower():
                if path == current:
                    raise ValueError("O repositório dos votos difere do informado.")
                continue
            head = review.get("head_sha")
            if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
                raise ValueError("O registro deve conter o SHA completo da PR.")
            findings = unanimous_findings(review)
        except (OSError, ValueError) as error:
            if path == current:
                raise
            result["lacunas"].append({"arquivo": path.name, "motivo": str(error)})
            continue

        for finding in findings:
            occurrence = {
                "pr": number, "url": f"https://github.com/{repo}/pull/{number}",
                "head_sha": head, "id": finding.get("id"),
                "file": finding["file"], "line": finding["line"], "scenario": finding["scenario"],
            }
            cause = finding["cause"]
            key = (cause["file"], cause["line"], cause["fragment"]) if cause else None
            if key:
                occurrence["evidencia_origem"] = cause["evidence"]
                by_cause[key].append((occurrence, cause))
            pattern = finding.get("pattern")
            if isinstance(pattern, str) and normalize_pattern(pattern):
                by_pattern[normalize_pattern(pattern)].append((occurrence, key))

    for group in by_cause.values():
        prs = {item["pr"] for item, _ in group}
        if current_pr in prs and len(prs) > 1:
            origin = next(cause for item, cause in group if item["pr"] == current_pr)
            result["propostas"].append({
                "origem": origin,
                "ocorrencias": sorted((item for item, _ in group), key=lambda item: item["pr"]),
            })
    for pattern, group in by_pattern.items():
        current_keys = {key for item, key in group if item["pr"] == current_pr}
        candidates = [
            item for item, key in group
            if item["pr"] != current_pr
            and current_keys
            and (key is None or None in current_keys)
        ]
        if candidates:
            candidates.extend(item for item, _ in group if item["pr"] == current_pr)
            result["suspeitas"].append({
                "padrao": pattern, "ocorrencias": sorted(candidates, key=lambda item: item["pr"]),
            })
    return result


def main():
    parser = argparse.ArgumentParser(description="Compara achados unânimes entre PRs.")
    parser.add_argument("repo")
    parser.add_argument("number", type=int)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", args.repo) or args.number < 1:
        parser.error("Informe um repositório owner/name e um número positivo de PR.")
    try:
        result = detect_recurrence(Path("factory/jobs"), args.repo, args.number)
    except (OSError, ValueError) as error:
        sys.exit(f"Falha na análise de recorrência: {error}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
