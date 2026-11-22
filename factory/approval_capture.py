import hashlib
import json
from pathlib import Path
import sys


DECISIONS = {"APROVADO", "VOLTAR"}


def parse_verdict(text):
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    try:
        verdict = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return verdict if isinstance(verdict, dict) else None


def decide(payload, context, jobs):
    events = [json.loads(line) for line in (jobs / "aprovacao-eventos.jsonl").read_text(encoding="utf-8").splitlines()]
    reviewers = [event["agent_id"] for event in events
                 if event.get("agent_type") == context["reviewer_agent_type"] and event.get("agent_id")]
    record = {
        "decision": "ESCALAR", "origin": "claude-code-hook", "approval_event": "SubagentStop",
        "approver_session": payload.get("agent_id"), "reviewer_session": reviewers[-1] if reviewers else None,
        "builder_session": context["builder_session"], "base_sha": context["base_sha"],
        "diff_sha256": context["diff_sha256"],
    }
    reasons = []
    if not payload.get("agent_id"):
        reasons.append("evento sem agent_id")
    if payload.get("session_id") != context["builder_session"]:
        reasons.append("sessão de origem difere do Builder")
    if not reviewers:
        reasons.append("evento do revisor ausente")
    computed = hashlib.sha256(Path(context["diff_path"]).read_bytes()).hexdigest()
    if computed != context["diff_sha256"]:
        reasons.append("diff em disco difere do registrado")
    verdict = parse_verdict(payload.get("last_assistant_message"))
    if verdict is None:
        reasons.append("sem decisão JSON do aprovador")
    else:
        if verdict.get("base_sha") != context["base_sha"]:
            reasons.append("base informada pelo aprovador difere")
        if verdict.get("diff_sha256") != computed:
            reasons.append("SHA-256 informado pelo aprovador difere do diff")
        if verdict.get("decision") not in DECISIONS:
            reasons.append("decisão fora de APROVADO/VOLTAR")
    if not reasons:
        record["decision"] = verdict["decision"]
    record["reasons"] = reasons
    return record


def main():
    payload = json.load(sys.stdin)
    jobs = Path(payload["cwd"]) / "factory" / "jobs"
    context_path = jobs / "aprovacao-em-curso.json"
    if not context_path.exists():
        return
    context = json.loads(context_path.read_text(encoding="utf-8"))
    event = {key: payload.get(key) for key in ("agent_id", "agent_type", "session_id")}
    with (jobs / "aprovacao-eventos.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(event) + "\n")
    if payload.get("agent_type") == context["approver_agent_type"]:
        record = decide(payload, context, jobs)
        target = Path(payload["cwd"]) / context["record_path"]
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
