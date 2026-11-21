import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from review_filter import filter_findings


def github_api(endpoint, *, payload=None, paginate=False, method="POST"):
    args = ["gh", "api", "--hostname", "github.com", endpoint]
    if paginate:
        args.extend(["--paginate", "--slurp"])
    if payload is not None:
        args.extend(["--method", method, "--input", "-"])
    response = subprocess.run(
        args,
        input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(response.stdout)


def publish_review(api, repo, number, review):
    if not isinstance(review, dict) or str(review.get("repo", "")).lower() != repo.lower():
        raise ValueError("O repositório dos votos difere do repositório informado.")
    base = review.get("base_sha")
    head = review.get("head_sha")
    if not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("Informe os SHAs completos da base e da PR.")
    filtered = filter_findings(review.get("validators"), review.get("findings"))
    result = {
        "estado": "concluido", "publicados": [], "existentes": [],
        "pendentes": [], "internos": filtered["internos"],
    }
    endpoint = f"repos/{repo}/pulls/{number}"
    comments_endpoint = f"{endpoint}/comments"

    def check_version():
        pr = api(endpoint)
        if pr["state"] != "open":
            result["estado"] = "pr_fechada"
        elif (pr["base"]["sha"], pr["head"]["sha"]) != (base, head):
            result["estado"] = "desatualizado"
        return result["estado"] != "pr_fechada" and result["estado"] != "desatualizado"

    if not check_version():
        return result

    by_location = {}
    for finding in filtered["publicaveis"]:
        location = (finding["file"], finding["line"])
        label = finding["label"]
        evidence = finding["evidence"]
        impact = finding["impact"]
        identity = [label, " ".join(evidence.split()), " ".join(impact.split())]
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        finding_marker = f"<!-- factory-finding:{key} -->"
        details = f"{evidence}\n\n{impact}"
        body = f'**{label.capitalize()}:** {finding["scenario"]}\n\n{details}'
        by_location.setdefault(location, {})[finding_marker] = (body, details)

    if not by_location:
        return result
    existing = [
        comment for page in api(comments_endpoint, paginate=True) for comment in page
    ]
    for (path, line), findings in by_location.items():
        # A posição no mesmo commit continua estável quando a redação muda entre rodadas.
        key = hashlib.sha256(json.dumps([base, head, path, line]).encode()).hexdigest()
        marker = f"<!-- factory-review:{key} -->"
        location = {"file": path, "line": line}
        prior = next((item for item in existing if item["body"].endswith(marker)), None)
        previous = prior["body"].removesuffix(marker).rstrip() if prior else ""
        legacy = previous.split("<!-- factory-finding:", 1)[0]
        additions = [
            f"{body}\n\n{finding_marker}"
            for finding_marker, (body, details) in findings.items()
            if finding_marker not in previous
            and details not in legacy
        ]
        if prior is not None and not additions:
            result["existentes"].append({**location, "url": prior["html_url"]})
            continue
        if not check_version():
            break
        try:
            body = "\n\n".join(filter(None, [previous, *additions, marker]))
            if prior is None:
                comment = api(comments_endpoint, payload={
                    "body": body, "path": path, "line": line, "side": "RIGHT", "commit_id": head,
                })
            else:
                comment = api(f"repos/{repo}/pulls/comments/{prior['id']}",
                              payload={"body": body}, method="PATCH")
        except subprocess.CalledProcessError as error:
            result["estado"] = "pendente"
            result["pendentes"].append({**location, "motivo": error.stderr.strip()})
        else:
            result["publicados"].append({**location, "url": comment["html_url"]})
    return result


def main():
    parser = argparse.ArgumentParser(description="Publica achados unânimes na PR.")
    parser.add_argument("repo")
    parser.add_argument("number", type=int)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", args.repo) or args.number < 1:
        parser.error("Informe um repositório owner/name e um número positivo de PR.")
    lock_path = Path("factory/jobs") / f'.{args.repo.lower().replace("/", "-")}-{args.number}.lock'
    try:
        review = json.load(sys.stdin)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = publish_review(github_api, args.repo, args.number, review)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"Falha na publicação da revisão: {getattr(error, 'stderr', None) or error}")


if __name__ == "__main__":
    main()
