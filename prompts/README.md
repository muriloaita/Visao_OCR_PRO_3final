# Prompt mestre do modo extrato

Esta pasta é montada no container em `/app/prompts` e **não é versionada**
(exceto este README), porque o repositório é público.

Na VPS, crie aqui o arquivo `prompt_mestre_extrato.md` com o texto do prompt
mestre de auditoria forense (a constante `PROMPT_MESTRE_EXTRATO` da versão
anterior do app). Os marcadores abaixo são substituídos a cada requisição:

| Marcador | Valor |
|---|---|
| `{ocr_texto}` | Texto extraído do PDF |
| `{data_inicio}` | Campo `data_inicio` enviado pelo SysMG |
| `{data_fim}` | Campo `data_fim` enviado pelo SysMG |
| `{filtro}` | Campo `filtro` enviado pelo SysMG |

Sem esse arquivo, a rota `/extrato` responde com erro e `/health` mostra
`"prompt_extrato_ok": false`. A rota `/ocr` funciona normalmente.
