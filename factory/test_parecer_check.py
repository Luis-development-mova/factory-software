import unittest

from parecer_check import missing_sections

COMPLETE = """# Parecer local · PR #1

## Lacunas

- Nada.

## Evidência

### Validado
- Suíte rodou 40 casos no SHA avaliado.

### Simulado
- API do GitHub substituída por registros locais.

### Pendente
- Nenhum.

## Publicação

Estado: `concluido`.
"""

WITHOUT_SIMULATED = COMPLETE.replace("### Simulado\n- API do GitHub substituída por registros locais.\n\n", "")

NO_EVIDENCE_SECTION = """# Parecer local · PR #18

## Lacunas

- A API simulada não foi declarada como evidência separada.
"""


class ParecerCheckTest(unittest.TestCase):
    def test_complete_parecer_has_no_missing_sections(self):
        self.assertEqual(missing_sections(COMPLETE), [])

    def test_missing_simulated_subsection_is_reported(self):
        self.assertEqual(missing_sections(WITHOUT_SIMULATED), ["Simulado"])

    def test_parecer_without_evidence_section_reports_all_three(self):
        self.assertEqual(missing_sections(NO_EVIDENCE_SECTION), ["Validado", "Simulado", "Pendente"])

    def test_subsection_in_a_later_section_does_not_count(self):
        text = NO_EVIDENCE_SECTION + "\n## Publicação\n\n### Validado\n### Simulado\n### Pendente\n"
        self.assertEqual(missing_sections(text), ["Validado", "Simulado", "Pendente"])
