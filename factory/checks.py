import subprocess

from check_demo import CHECKS


def main():
    failed = False
    for number, check in sorted(CHECKS.items()):
        try:
            failure = check()
        except (OSError, subprocess.SubprocessError) as error:
            failure = f"Não foi possível executar o teste: {error}"
        if failure:
            failed = True
            print(f"#{number} FALHOU · {failure}")
        else:
            print(f"#{number} PASSOU")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
