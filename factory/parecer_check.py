import re
import sys
from pathlib import Path

REQUIRED = ("Validado", "Simulado", "Pendente")
EVIDENCE_SECTION = re.compile(r"^## Evidência[ \t]*$", re.MULTILINE)
NEXT_SECTION = re.compile(r"^## ", re.MULTILINE)
SUBSECTION = re.compile(r"^### (.+?)[ \t]*$", re.MULTILINE)


def missing_sections(text):
    start = EVIDENCE_SECTION.search(text)
    if not start:
        return list(REQUIRED)
    body = text[start.end():]
    end = NEXT_SECTION.search(body)
    if end:
        body = body[:end.start()]
    found = {title.casefold() for title in SUBSECTION.findall(body)}
    return [name for name in REQUIRED if name.casefold() not in found]


def main(argv):
    if len(argv) != 2:
        print("Uso: python3 factory/parecer_check.py <parecer.md>", file=sys.stderr)
        return 2
    missing = missing_sections(Path(argv[1]).read_text(encoding="utf-8"))
    if missing:
        print("Parecer sem evidência separada · faltando: " + ", ".join(missing))
        return 1
    print("Parecer com Validado, Simulado e Pendente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
