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


def resolve(payload, events):
    bound = [e for e in events if e.get("kind") == "SubagentHandback"
             and e.get("agent_id") == payload.get("agent_id") and e.get("session_id") == payload.get("session_id")]
    sources = {"last_assistant_message": parse_verdict(payload.get("last_assistant_message")),
               "SubagentHandback.tool_input.message": parse_verdict(bound[-1].get("message")) if bound else None}
    found = {name: value for name, value in sources.items() if value}
    if not found:
        return None, "decisão ausente"
    if len({tuple(value.get(field) for field in FIELDS) for value in found.values()}) > 1:
        return None, "fontes divergentes: " + ", ".join(found)
    return next(iter(found.values())), "+".join(found)


def decide(approver, reviewer, context):
    computed = hashlib.sha256(Path(context["diff_path"]).read_bytes()).hexdigest()
    verdict, reasons = approver.get("verdict"), []
    if not approver.get("agent_id"):
        reasons.append("evento sem agent_id")
    if approver.get("session_id") != context["builder_session"]:
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
    return {"decision": "ESCALAR" if reasons else verdict["decision"], "origin": "claude-code-hook",
            "approval_event": "SubagentStop", "approver_session": approver.get("agent_id"),
            "reviewer_session": reviewer.get("agent_id"), "builder_session": context["builder_session"],
            "base_sha": context["base_sha"], "diff_sha256": context["diff_sha256"], "reasons": reasons}


def append(path, event):
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(event, ensure_ascii=False) + "\n")


def main():
    payload = json.load(sys.stdin)
    root = Path(payload["cwd"])
    jobs = root / "factory" / "jobs"
    if not (jobs / "aprovacao-em-curso.json").exists():
        return
    context = json.loads((jobs / "aprovacao-em-curso.json").read_text(encoding="utf-8"))
    log = jobs / "aprovacao-eventos.jsonl"
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    if payload.get("hook_event_name") == "PostToolUse":
        if payload.get("tool_name") == "SubagentHandback":
            append(log, {"kind": "SubagentHandback", "agent_id": payload.get("agent_id"),
                         "session_id": payload.get("session_id"), "message": (payload.get("tool_input") or {}).get("message")})
        return
    event = {key: payload.get(key) for key in ("agent_id", "agent_type", "session_id")}
    if event["agent_type"] == context["approver_agent_type"]:
        event["verdict"], event["verdict_note"] = resolve(payload, events)
    append(log, event)
    events.append(event)
    approvers = [e for e in events if e.get("agent_type") == context["approver_agent_type"]]
    reviewers = [e for e in events if e.get("agent_type") == context["reviewer_agent_type"] and e.get("agent_id")]
    if approvers and reviewers:
        record = decide(approvers[-1], reviewers[-1], context)
        (root / context["record_path"]).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
