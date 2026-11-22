import hashlib
import json
from pathlib import Path
import sys


DECISIONS = {"APROVADO", "VOLTAR"}
FIELDS = ("decision", "base_sha", "diff_sha256")


def parse_verdict(text):
    if not isinstance(text, str):
        return None
    try:
        verdict = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except ValueError:
        return None
    return verdict if isinstance(verdict, dict) else None


def handback(path):
    if not path or not Path(path).exists():
        return None
    found = None
    for entry in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()):
        parts = (entry.get("message") or {}).get("content")
        for part in parts if isinstance(parts, list) else []:
            if isinstance(part, dict) and part.get("name") == "SubagentHandback":
                found = {"message": part.get("input", {}).get("message"),
                         "agent_id": entry.get("agentId"), "session_id": entry.get("sessionId")}
    return found


def resolve(payload):
    hand = handback(payload.get("agent_transcript_path"))
    sources = {"last_assistant_message": parse_verdict(payload.get("last_assistant_message")),
               "SubagentHandback.input.message": parse_verdict(hand and hand["message"])}
    found = {name: value for name, value in sources.items() if value}
    if not found:
        return None, "decisão ausente", hand
    if len({tuple(value.get(field) for field in FIELDS) for value in found.values()}) > 1:
        return None, "fontes divergentes: " + ", ".join(found), hand
    return next(iter(found.values())), "+".join(found), hand


def decide(approver, reviewer, context):
    hand = approver.get("handback") or {}
    ids = {approver.get("agent_id"), approver.get("transcript_agent_id"), hand.get("agent_id")} - {None}
    sessions = {approver.get("session_id"), hand.get("session_id")} - {None}
    computed = hashlib.sha256(Path(context["diff_path"]).read_bytes()).hexdigest()
    verdict, reasons = approver.get("verdict"), []
    if ids != {approver.get("agent_id")} or approver.get("agent_id") is None:
        reasons.append("agent_id ausente ou divergente entre evento e transcrição")
    if sessions != {context["builder_session"]}:
        reasons.append("sessão de origem difere do Builder")
    if computed != context["diff_sha256"]:
        reasons.append("diff em disco difere do registrado")
    if verdict is None:
        reasons.append(approver.get("verdict_note") or "sem decisão do aprovador")
    elif verdict.get("base_sha") != context["base_sha"]:
        reasons.append("base informada pelo aprovador difere")
    elif verdict.get("diff_sha256") != computed:
        reasons.append("SHA-256 informado pelo aprovador difere do diff")
    elif verdict.get("decision") not in DECISIONS:
        reasons.append("decisão fora de APROVADO/VOLTAR")
    decision = verdict["decision"] if not reasons else "ESCALAR"
    return {"decision": decision, "origin": "claude-code-hook", "approval_event": "SubagentStop",
            "approver_session": approver.get("agent_id"), "reviewer_session": reviewer.get("agent_id"),
            "builder_session": context["builder_session"], "base_sha": context["base_sha"],
            "diff_sha256": context["diff_sha256"], "reasons": reasons}


def main():
    payload = json.load(sys.stdin)
    root = Path(payload["cwd"])
    jobs = root / "factory" / "jobs"
    if not (jobs / "aprovacao-em-curso.json").exists():
        return
    context = json.loads((jobs / "aprovacao-em-curso.json").read_text(encoding="utf-8"))
    event = {key: payload.get(key) for key in ("agent_id", "agent_type", "session_id")}
    transcript = payload.get("agent_transcript_path")
    if event["agent_type"] == context["approver_agent_type"]:
        event["verdict"], event["verdict_note"], event["handback"] = resolve(payload)
        event["transcript_agent_id"] = Path(transcript).stem.removeprefix("agent-") if transcript else None
    with (jobs / "aprovacao-eventos.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(event, ensure_ascii=False) + "\n")
    events = [json.loads(line) for line in (jobs / "aprovacao-eventos.jsonl").read_text(encoding="utf-8").splitlines()]
    approvers = [e for e in events if e.get("agent_type") == context["approver_agent_type"]]
    reviewers = [e for e in events if e.get("agent_type") == context["reviewer_agent_type"] and e.get("agent_id")]
    if approvers and reviewers:
        record = decide(approvers[-1], reviewers[-1], context)
        (root / context["record_path"]).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
