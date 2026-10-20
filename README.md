# Visão OCR Pro — serviço de extração para o SysMG

Extrai o texto de PDFs (extratos, contratos) para o SysMG:

- **Páginas digitais** (com texto embutido): leitura direta pelo PyMuPDF, praticamente instantânea.
- **Páginas escaneadas** (imagem): OCR com Tesseract, em português, a 300 DPI.

O serviço devolve apenas o texto em JSON. A tela e a geração de PDF ficam com o SysMG.

## Arquitetura

```
SysMG (PHP, hospedagem Cloud)                VPS (Docker)
  sysmg/OcrClient.php  ── HTTPS + token ──▶  Caddy (certificado automático)
                                               └─▶ gunicorn → ocr_server.py → Tesseract
```

## Consumo medido

Teste com extrato sintético de 10 páginas A4 escaneadas (300 DPI), no container deste repositório:

| Situação | Tempo | Memória do container (pico) |
|---|---|---|
| 1 extrato escaneado de 10 páginas | ~35 s (~3,5 s/página) | ~400 MB |
| 2 extratos simultâneos | ~35 s cada, em paralelo | ~800 MB |
| 1 PDF digital de 10 páginas | 0,04 s | — |

Cada processo do gunicorn atende um PDF por vez. Com `GUNICORN_WORKERS=2` (KVM 2, 2 vCPU),
até 2 extratos são processados ao mesmo tempo; os demais aguardam na fila.
Imagem Docker: ~470 MB.

## Implantação na VPS

1. **DNS** — no hPanel, na zona DNS do domínio, crie um registro `A` com nome `ocr`
   apontando para o IP da VPS.

2. **Código** — por SSH na VPS:
   ```bash
   git clone https://github.com/muriloaita/Visao_OCR_PRO_3final.git
   cd Visao_OCR_PRO_3final
   cp .env.example .env
   openssl rand -hex 32   # copie o resultado para OCR_API_TOKEN no .env
   nano .env              # ajuste também OCR_DOMAIN (ex.: ocr.seudominio.com.br)
   ```

3. **Prompt mestre** — crie `prompts/prompt_mestre_extrato.md` (ver `prompts/README.md`).
   Ele fica só no servidor, pois este repositório é público.

4. **Subir** — confira se as portas 80 e 443 estão livres:
   ```bash
   sudo ss -ltnp | grep -E ':(80|443) '
   ```
   - Nada listado → `docker compose --profile https up -d --build`
   - Já ocupadas por outro proxy (ex.: Traefik) → `docker compose up -d --build` e configure
     esse proxy para encaminhar o subdomínio ao serviço `ocr`, porta 5001.

   Se o firewall da VPS estiver ativo no hPanel, libere as portas 80 e 443.

5. **Teste**:
   ```bash
   curl https://ocr.seudominio.com.br/health
   ```
   Esperado: `"tesseract_ok": true` e `"prompt_extrato_ok": true`.

Atualizar depois: `git pull && docker compose --profile https up -d --build`.

## Integração com o SysMG

Copie `sysmg/OcrClient.php` para o SysMG. Guarde o token fora do `public_html`
(arquivo de configuração ou variável de ambiente), nunca no código versionado.

```php
require_once 'OcrClient.php';
$ocr = new OcrClient('https://ocr.seudominio.com.br', $tokenOcr);

$r = $ocr->ocr($caminhoDoPdf);
// $r['texto'], $r['total_paginas'], $r['paginas_ocr'], $r['paginas'] (detalhe por página)

$r = $ocr->extrato($caminhoDoPdf, '01/01/2020', '31/12/2020', 'TODOS OS LANÇAMENTOS');
// $r['prompt_forense'] = prompt mestre com o texto extraído embutido
```

Extratos longos escaneados levam minutos (100 páginas ≈ 6 min). Nesses casos, prefira
disparar a extração em segundo plano (cron/fila do SysMG) em vez de segurar a página do usuário.

## Rotas

| Rota | Método | Token | Retorno |
|---|---|---|---|
| `/health` | GET | não | Status do Tesseract e do prompt |
| `/ocr` | POST (`file`) | sim | `texto`, `total_paginas`, `paginas_digitais`, `paginas_ocr`, `paginas`, `chars_totais` |
| `/extrato` | POST (`file`, `data_inicio`, `data_fim`, `filtro`) | sim | Idem + `prompt_forense` e `parametros` |

Token: header `Authorization: Bearer <OCR_API_TOKEN>`.

## Observação

Texto obtido por OCR está sujeito a erros de reconhecimento e deve ser conferido com o
documento original antes de uso em cálculo ou peça.
