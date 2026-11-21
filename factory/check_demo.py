import argparse
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from intake import JOBS, save


class Heading(HTMLParser):
    inside = False
    parts = None

    def handle_starttag(self, tag, attrs):
        if tag == "h1" and self.parts is None:
            self.parts = []
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "h1":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


PAGE = Path(__file__).resolve().parents[1] / "index.html"


def read_browser_dom(page):
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    with TemporaryDirectory() as profile:
        result = subprocess.run(
            [str(chrome), "--headless", f"--user-data-dir={profile}", "--dump-dom", page.as_uri()],
            capture_output=True, text=True, encoding="utf-8", check=True, timeout=30,
        )
    return result.stdout


def check_greeting():
    if not PAGE.is_file():
        return "Aceite da issue #1 falhou: index.html ainda não existe."
    heading = Heading()
    heading.feed(read_browser_dom(PAGE))
    if "".join(heading.parts or []) != "Olá, fábrica!":
        return "Aceite da issue #1 falhou: o título no navegador deve ser “Olá, fábrica!”."


def check_subtitle():
    if not PAGE.is_file():
        return "Aceite da issue #2 falhou: index.html ainda não existe."
    dom = read_browser_dom(PAGE)
    if not re.search(r"<h1>Olá, fábrica!</h1>\s*<(p|h2)>A fábrica está funcionando\.</\1>", dom):
        return "Aceite da issue #2 falhou: falta o subtítulo “A fábrica está funcionando.” logo abaixo do título."


def check_panel_link():
    dom = read_browser_dom(PAGE)
    if not re.search(r'<a\s+href="factory/jobs/index\.html">Ver o painel</a>', dom):
        return "Aceite da issue #3 falhou: falta o link “Ver o painel” para o painel da triagem."
    if "Triagem da fábrica" not in read_browser_dom(JOBS / "index.html"):
        return "Aceite da issue #3 falhou: o destino não mostrou o painel da triagem."


def check_operation_note():
    dom = read_browser_dom(PAGE)
    if not re.search(
        r'<a\b[^>]*>Ver o painel</a>[\s\S]*?<footer\b[^>]*>\s*'
        r'<p>Acompanhe a operação na esteira da fábrica\.</p>\s*</footer>',
        dom,
    ):
        return "Aceite da issue #22 falhou: falta a nota de operação no rodapé abaixo de “Ver o painel”."


CHECKS = {1: check_greeting, 2: check_subtitle, 3: check_panel_link}
ACCEPTANCE_CHECKS = {22: check_operation_note}


def main():
    parser = argparse.ArgumentParser(description="Executa o teste de aceite local de uma issue.")
    parser.add_argument("issue", type=int, nargs="?", default=1)
    number = parser.parse_args().issue
    check = ACCEPTANCE_CHECKS.get(number) or CHECKS.get(number)
    if check is None:
        sys.exit(f"A issue #{number} ainda não tem teste de aceite cadastrado.")

    try:
        job = JOBS / f"{number}.json"
        ticket = json.loads(job.read_text())["ticket"] if job.is_file() else None
        failure = check()
        message = failure or f"Aceite da issue #{number} passou."
        if ticket is not None:
            save(JOBS / f"{number}-aceite.json", json.dumps({"ticket": ticket, "message": message}))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"Não foi possível concluir o teste da issue #{number}: {error}")
    if failure:
        sys.exit(failure)
    print(message)


if __name__ == "__main__":
    main()
