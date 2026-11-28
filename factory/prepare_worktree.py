import argparse
import fcntl
import os
import re
import subprocess
import sys
from pathlib import Path


def git(repo, *args):
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return result.stdout


def git_path(repo, option):
    value = git(repo, "rev-parse", "--path-format=absolute", option)
    return Path(os.fsdecode(value.removesuffix(b"\n"))).resolve()


def prepare(repo, issue, base):
    common = git_path(repo, "--git-common-dir")
    with (common / "factory-worktrees.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if git(repo, "cat-file", "-t", base) != b"commit\n":
            raise ValueError("O SHA da base precisa apontar para um commit.")

        listing = git(repo, "worktree", "list", "--porcelain", "-z")
        records = [entry.split(b"\0") for entry in listing.split(b"\0\0") if entry]
        if not records or b"bare" in records[0]:
            raise ValueError("Informe um checkout de um repositório Git com diretório de trabalho.")
        primary = Path(os.fsdecode(records[0][0].removeprefix(b"worktree ")))
        parent = primary.with_name(f"{primary.name}.factory-worktrees")
        checkout = parent / f"issue-{issue}"
        if parent.is_symlink() or checkout.is_symlink():
            raise ValueError(f"Caminho reservado contém um link simbólico: {checkout}.")

        registered = any(entry[0] == b"worktree " + os.fsencode(checkout) for entry in records)
        if not registered:
            if checkout.exists():
                raise ValueError(f"O caminho já existe sem uma worktree registrada: {checkout}.")
            parent.mkdir(exist_ok=True)
            git(repo, "worktree", "add", "--detach", "--", str(checkout), base)

        if not checkout.is_dir() or git_path(checkout, "--show-toplevel") != checkout:
            raise ValueError(f"A worktree registrada não está disponível em {checkout}.")
        if git_path(checkout, "--git-common-dir") != common:
            raise ValueError(f"A worktree em {checkout} pertence a outro repositório.")
        if (git(checkout, "branch", "--show-current")
                or git(checkout, "rev-parse", "HEAD").strip() != base.encode("ascii")):
            raise ValueError(f"A worktree em {checkout} precisa estar destacada no SHA da base {base}.")
        if git(checkout, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"):
            raise ValueError(f"A worktree em {checkout} tem alterações pendentes.")
        return checkout


def main():
    parser = argparse.ArgumentParser(description="Prepara a worktree local de uma issue da Factory.")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"0*[1-9][0-9]*", args.issue):
        parser.error("--issue precisa ser um inteiro positivo escrito com dígitos ASCII.")
    if not re.fullmatch(r"[0-9a-f]{40}", args.base):
        parser.error("--base precisa ser o SHA completo da base no GitHub.")
    try:
        print(prepare(args.repo, args.issue.lstrip("0"), args.base))
    except subprocess.CalledProcessError as error:
        sys.exit(f"Falha ao preparar a worktree: {os.fsdecode(error.stderr).strip() or error}")
    except (OSError, ValueError) as error:
        sys.exit(f"Falha ao preparar a worktree: {error}")


if __name__ == "__main__":
    main()
