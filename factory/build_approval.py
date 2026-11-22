import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def check_approval(record, base, diff):
    if not isinstance(record, dict) or record.get("decision") != "APROVADO":
        raise ValueError("Falta um parecer independente APROVADO.")
    sessions = [record.get(key) for key in ("reviewer_session", "approver_session")]
    if not all(isinstance(session, str) and session.strip() for session in sessions):
        raise ValueError("Registre os identificadores do revisor e do aprovador.")
    if sessions[0].strip().casefold() == sessions[1].strip().casefold():
        raise ValueError("O revisor e o aprovador devem ser sessões distintas.")
    if not re.fullmatch(r"[0-9a-f]{40}", base) or record.get("base_sha") != base:
        raise ValueError("A base atual difere da base avaliada.")
    if not diff or record.get("diff_sha256") != hashlib.sha256(diff).hexdigest():
        raise ValueError("O diff a publicar está vazio ou difere do diff aprovado.")


def main():
    parser = argparse.ArgumentParser(description="Confere a aprovação antes de enviar uma PR.")
    parser.add_argument("record", type=Path)
    parser.add_argument("base")
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        check_approval(record, args.base, sys.stdin.buffer.read())
    except (OSError, ValueError) as error:
        sys.exit(f"Abertura da PR pendente: {error}")
    print("Aprovação independente confere com a base e o diff.")


if __name__ == "__main__":
    main()
