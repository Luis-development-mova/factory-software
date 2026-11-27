import argparse
import os
import subprocess
import sys


LIMIT = 300
GIT = ["git", "--no-replace-objects"]
LINE_MODES = {b"000000", b"100644", b"100755", b"120000"}


def git(*args):
    return subprocess.run([*GIT, *args], stdout=subprocess.PIPE, check=True).stdout


def parse_diff(report):
    changed, blobs = set(), {}
    additions = deletions = 0
    if report and not report.endswith(b"\0"):
        raise ValueError("Relatório do Git incompleto.")
    records = iter(report.split(b"\0")[:-1])
    for record in records:
        if record.startswith(b":"):
            old_mode, new_mode, old_oid, new_oid, status = record[1:].split()
            path = next(records, b"")
            if not path or status not in {b"A", b"D", b"M", b"T"}:
                raise ValueError(f"Alteração inconclusiva em {os.fsdecode(path)!r}.")
            if {old_mode, new_mode} - LINE_MODES:
                raise ValueError(f"Tipo de arquivo sem contagem de linhas em {os.fsdecode(path)!r}.")
            changed.add(path)
            for mode, oid in ((old_mode, old_oid), (new_mode, new_oid)):
                if mode != b"000000":
                    blobs[oid.decode("ascii")] = path
            continue

        added, removed, path = record.split(b"\t", 2)
        if not added.isdigit() or not removed.isdigit():
            raise ValueError(f"Arquivo binário ou sem contagem de linhas: {os.fsdecode(path)!r}.")
        if path not in changed:
            raise ValueError(f"Contagem inconsistente em {os.fsdecode(path)!r}.")
        changed.remove(path)
        additions += int(added)
        deletions += int(removed)
    if changed:
        raise ValueError("Faltam contagens no relatório do Git.")
    return additions, deletions, blobs


def check_blobs(blobs):
    for oid, path in blobs.items():
        # Um atributo diff pode forçar numstat a tratar um binário como texto.
        with subprocess.Popen([*GIT, "cat-file", "blob", oid], stdout=subprocess.PIPE) as blob:
            for chunk in iter(lambda: blob.stdout.read(65536), b""):
                if b"\0" in chunk:
                    blob.kill()
                    raise ValueError(f"Arquivo binário: {os.fsdecode(path)!r}.")
            if blob.wait():
                raise ValueError(f"Não foi possível ler o conteúdo de {os.fsdecode(path)!r}.")


def main():
    parser = argparse.ArgumentParser(description="Verifica o limite de adições e exclusões de uma PR.")
    parser.add_argument("--base", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--head")
    target.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    try:
        head_ref = "HEAD" if args.staged else args.head
        if not args.base or not head_ref:
            raise ValueError("Informe referências válidas para a base e a versão avaliada.")
        if git("rev-parse", "--is-shallow-repository").strip() != b"false":
            raise ValueError("Use um checkout com histórico completo para determinar o ancestral comum.")
        base = git("rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}").decode().strip()
        head = git("rev-parse", "--verify", "--end-of-options", f"{head_ref}^{{commit}}").decode().strip()
        ancestors = git("merge-base", "--all", base, head).decode().splitlines()
        if len(ancestors) != 1:
            raise ValueError("O Git não encontrou um ancestral comum único.")
        ancestor = ancestors[0]
        diff_target = ("--cached", ancestor) if args.staged else (ancestor, head)
        report = git(
            "diff", "--raw", "--numstat", "-z", "--no-abbrev", "--no-renames", "--no-color",
            "--no-ext-diff", "--no-textconv", "--no-relative", "--ignore-submodules=none",
            "--diff-algorithm=myers", "--indent-heuristic", *diff_target, "--",
        )
        additions, deletions, blobs = parse_diff(report)
        check_blobs(blobs)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"PR bloqueada. Contagem inconclusiva: {error} Encaminhe para decisão humana.", file=sys.stderr)
        return 2

    version = f"índice (HEAD {head})" if args.staged else head
    total = additions + deletions
    print(f"Base {base} | ancestral {ancestor} | versão {version}")
    print(f"Adições {additions} | exclusões {deletions} | total {total} | limite {LIMIT}")
    if total > LIMIT:
        print("PR bloqueada. Proponha uma decomposição para aprovação humana.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
