# Manual de revisão da fábrica

## Grupo 1 · Encontrar problemas

Leia a descrição da PR e a issue vinculada. Identifique o objetivo e os critérios de aceite. Compare o diff com o pedido e siga os fluxos afetados pelo repositório, inclusive fora do diff. Confira chamadas, testes, configurações e documentação.

Procure diferenças que tenham efeito real. Por exemplo, o README diz que uma opção vem ligada, mas o código a deixa desligada. Outro exemplo é uma configuração de testes que aponta para produção.

Para cada achado, registre arquivo, linha, cenário afetado, evidência e impacto. Use `importante` para problema sério, `nitpick` para detalhe pequeno com efeito concreto e `já existente` quando a falha também ocorre na base. Limite de três nitpicks por revisor. Descarte preferências pessoais de estilo.

## Grupo 2 · Validar os achados

Agentes que não participaram da primeira revisão verificam cada achado por conta própria. Cada voto informa se a evidência sustenta o impacto descrito e por quê. Confirme também se a falha foi introduzida pela PR ou se já existia.

Só publique um comentário na PR quando todos os validadores concordarem que o problema é real e que a classificação está correta. Guarde divergências, falta de evidência e votos ausentes no parecer interno.

## Aprender com apontamentos repetidos

Quando o mesmo problema aparecer em mais de uma PR, confirme a recorrência e proponha uma correção na origem. Use lint ou teste se a regra for verificável. Para orientação de implementação, use `AGENTS.md`, `CLAUDE.md` ou a skill pertinente.

Quando for falso positivo, registre neste manual um exemplo, a justificativa e as condições em que a exceção vale.

## Como validar o filtro

No Claude Code, execute `/factory review <n>` para revisar uma PR. O orquestrador grava os votos e o parecer local em `factory/jobs/`, com os SHAs avaliados. O parecer contém as minutas dos achados unânimes e o registro dos achados internos.

Execute `python3 factory/review_filter.py < votos.json`. O orquestrador deve fixar o grupo antes da votação e fornecer `validators`, uma lista de identificadores distintos com pelo menos dois itens, e `findings` com os achados. Cada achado tem `file`, `line`, `scenario`, `evidence`, `impact`, `label`, `revisor` (identificador do revisor de origem, como `R1` ou `R2`) e `votes`. Cada voto tem `validator`, `confirmed` (verdadeiro apenas se confirma o problema e sua classificação) e `reason`.

Use a lista `publicaveis` para preparar comentários e guarde `internos` no parecer. O comando devolve as listas sem publicar no GitHub.

- Um achado com arquivo, linha e impacto confirmados por todos gera um comentário.
- Um achado com voto divergente ou ausente fica no parecer interno.
- Um achado malformado vai para `internos` com o motivo; os demais achados continuam sendo avaliados.
- No máximo três `nitpick` por revisor entram em `publicaveis`; o excedente vai para `internos`. `importante` e `já existente` não contam para o limite.
- Se `validators` não for uma lista de identificadores distintos, o filtro encerra com erro e nenhuma lista é devolvida.
