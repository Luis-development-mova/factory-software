import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ORIGIN = "orquestrador"
SESSION_FIELDS = ("builder_session", "reviewer_session", "approver_session")


def remote_base_sha(remote):
    try:
        result = subprocess.run(
            ["git", "ls-remote", remote, "HEAD"], capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"Não foi possível consultar a base remota: {error}") from error
    fields = result.stdout.split()
    if not fields:
        raise ValueError("O remoto não informou a base atual.")
    return fields[0]


def check_approval(record, base, diff, remote_base):
    if not isinstance(record, dict) or record.get("decision") != "APROVADO":
        raise ValueError("Falta um parecer independente APROVADO.")
    if record.get("origin") != ORIGIN:
        raise ValueError("A aprovação não tem origem verificável: o registro deve vir do orquestrador.")
    sessions = [record.get(key) for key in SESSION_FIELDS]
    if not all(isinstance(session, str) and session.strip() for session in sessions):
        raise ValueError("Registre os identificadores do Builder, do revisor e do aprovador.")
    normalized = [session.strip().casefold() for session in sessions]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Builder, revisor e aprovador devem ser sessões distintas.")
    if not re.fullmatch(r"[0-9a-f]{40}", base) or record.get("base_sha") != base:
        raise ValueError("A base informada difere da base avaliada no registro.")
    if remote_base != base:
        raise ValueError("A base remota atual difere da base aprovada.")
    if not diff or record.get("diff_sha256") != hashlib.sha256(diff).hexdigest():
        raise ValueError("O diff a publicar está vazio ou difere do diff aprovado.")


def main():
    parser = argparse.ArgumentParser(description="Confere a aprovação antes de enviar uma PR.")
    parser.add_argument("record", type=Path)
    parser.add_argument("base")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        check_approval(record, args.base, sys.stdin.buffer.read(), remote_base_sha(args.remote))
    except (OSError, ValueError) as error:
        sys.exit(f"Abertura da PR pendente: {error}")
    print("Aprovação independente confere com a base remota e o diff.")


if __name__ == "__main__":
    main()
