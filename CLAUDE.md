# Visão OCR Pro 3 — instruções para o Claude Code

Ferramenta interna da Marques & Gameiro Advocacia: OCR local de PDFs jurídicos
(Tesseract + PyMuPDF). **Versão 3 = somente OCR.** Os modos de extrato bancário
e de cartão (maquininha) foram retirados de propósito — não reintroduza
`extrato_parser.py`, `vendas_cartao.py` nem rotas `/extrato*`.

## Se pedirem para "rodar o app nesta máquina"

1. O caminho mais simples é o instalador: `VisaoOCRPro-Setup-<versão>.exe`
   (artefato do workflow *Instalador Windows*). Ele já traz Python embutido,
   site e Tesseract com português.
2. Pelo código-fonte (Windows):
   - Python 3.11+ (`python --version`); Tesseract com português em
     `C:\Program Files\Tesseract-OCR\` (ou numa pasta `Tesseract-OCR\` na raiz
     do projeto, que tem prioridade). Confirme com o usuário antes de instalar
     algo fora desta pasta ou que peça administrador.
   - `pip install -r requirements.txt`
   - Site: `npm install && npm run build` (gera `dist/`).
   - `python app_desktop.py` (ou `IniciarVisaoOCRPro.vbs`, sem console).
   - Confirme: `curl http://localhost:5002/api/ocr/health` → `"status": "online"`,
     `"tesseract_ok": true`, `"idioma_ok": true`.

## Arquitetura

- `ocr_server.py` — Flask; API (`/api/ocr/health`, `/api/ocr/processar`,
  `/api/ocr/paginas`) + site `dist/`. `BASE_DIR` = pasta do `.exe` quando congelado.
- `app_desktop.py` — entrada do `VisaoOCRPro.exe`: waitress em 127.0.0.1:5002,
  bandeja (pystray), navegador, instância única, `--processar-pasta`.
- `processar_pasta.py` — OCR em lote de uma pasta.
- `versao.py` — **única** fonte da versão (servidor, `.exe`, instalador).
- `src/App.tsx` — frontend; lotes de 25 páginas acima de 40 páginas.
- `instalador/` — `build.ps1` (pacote completo), `.spec` (PyInstaller),
  `.iss` (Inno Setup, AppId fixo, instala em `{autopf}\VisaoOCRPro` sem admin),
  `testar_instalador.ps1`.

## Antes de entregar uma mudança

- `python -m pytest -q` e `npm run lint` passando.
- Mudou dependência Python? O bundle congelado precisa continuar subindo:
  o workflow *Instalador Windows* testa o `.exe` e o Setup instalado.
- Nova versão: altere `versao.py` (e `package.json`) e descreva no `CHANGELOG.md`.

## Regras

- 100% local: sem chamadas a serviços externos, sem chave de API.
- O app instalado escuta só em 127.0.0.1. Não exponha a porta 5002 à internet.
- Textos da interface em português.
