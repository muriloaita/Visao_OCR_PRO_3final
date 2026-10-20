# Visão OCR Pro 3 — somente OCR

Ferramenta interna da **Marques & Gameiro Advocacia** para extrair texto de PDFs
jurídicos com **Tesseract OCR** + **PyMuPDF**. 100% local: nenhum documento sai
da máquina e não há chave de API.

A versão 3 é **só OCR**: os modos de extrato bancário e de extrato de cartão
(maquininha) da versão 2.0 foram retirados. O motor de OCR da 2.0 foi mantido
inteiro (veja o [CHANGELOG](CHANGELOG.md)).

## Instalar (usuários)

Baixe o **pacote completo** gerado pelo GitHub Actions
(aba *Actions* → *Instalador Windows* → último build → *Artifacts*):

| Arquivo | Para quê |
|---|---|
| `VisaoOCRPro-Setup-3.0.0.exe` | Instalador. Não pede administrador; instala em `%LOCALAPPDATA%\Programs\VisaoOCRPro` (mesma pasta da 2.0) e remove a versão antiga sozinho. |
| `VisaoOCRPro-3.0.0-portatil.zip` | Mesma coisa sem instalar: extraia e abra `VisaoOCRPro.exe`. |

O pacote já traz **tudo**: servidor OCR congelado (Python embutido), o site
pronto e o **Tesseract 5 com português**. A máquina não precisa de Python,
Node.js nem Tesseract.

Depois de instalado: atalho **Visão OCR Pro** → abre `http://localhost:5002`.
O ícone na bandeja (perto do relógio) tem *Abrir*, *Processar pasta de PDFs…*
e *Sair*.

## Funcionalidades

- **Detecção automática por página**: digital (PyMuPDF), escaneada (Tesseract)
  ou **mista** — rodapé digital + imagem escaneada, típica do PROJUDI.
- **Forçar OCR** em todas as páginas.
- **PDFs extensos** (mais de 40 páginas) processados em lotes de 25, com progresso
  e botão Cancelar; se um lote falhar, o texto extraído até ali é preservado.
- **Limpeza do OCR**: filtro de confiança por palavra, remoção de "salada" de
  caracteres (carimbos girados, bordas, assinaturas digitais), preservação de
  siglas (CNPJ, FGTS, TJPR…) e acentuação normalizada (NFC).
- **Exportação**: copiar, TXT, Markdown, PDF e ZIP (original + TXT + MD).
- **Pasta inteira**: gera `<nome>_texto.txt` ao lado de cada PDF e um
  `relatorio_lote.txt` (bandeja, Menu Iniciar ou `python processar_pasta.py <pasta>`).

## Estrutura

```
ocr_server.py          servidor Flask: API de OCR + site (dist/), porta 5002
app_desktop.py         inicializador do .exe: waitress + bandeja + navegador
processar_pasta.py     OCR de uma pasta inteira (CLI e bandeja)
versao.py              versão única do app (servidor, .exe e instalador)
src/                   frontend React (Vite + Tailwind)
tests/                 testes (pytest) — rodam também no build do instalador
instalador/
  build.ps1            gera o pacote completo (Setup + ZIP portátil)
  VisaoOCRPro.spec     PyInstaller
  VisaoOCRPro.iss      Inno Setup
  testar_instalador.ps1  teste ponta a ponta do Setup (instala, OCR, desinstala)
.github/workflows/instalador-windows.yml   build automático no Windows
```

### API

| Rota | Descrição |
|---|---|
| `GET /api/ocr/health` | status, versão do app, Tesseract e idiomas (`idioma_ok`) |
| `POST /api/ocr/processar` | `file` (PDF), `forcar_ocr`, `pagina_inicio`, `pagina_fim` |
| `POST /api/ocr/paginas` | só conta as páginas do PDF |

## Desenvolvimento

Requisitos: Python 3.11+, Node.js 18+ e Tesseract com o idioma português.

```bash
pip install -r requirements.txt -r requirements-build.txt
npm install

python ocr_server.py      # API em http://localhost:5002
npm run dev               # site em http://localhost:3000 (repassa /api para a 5002)

python -m pytest -q       # testes
npm run lint              # checagem de tipos
```

Para servir tudo numa porta só, como na versão instalada: `npm run build` e
`python app_desktop.py` (ou `IniciarVisaoOCRPro.vbs`, sem console).

## Gerar o instalador

**Automático:** todo push que altera o app dispara o workflow *Instalador
Windows*, que compila, testa, gera o Setup e o ZIP, instala o Setup numa
máquina Windows limpa, faz OCR e desinstala. Uma tag `v*` (ex.: `v3.0.0`) também
publica uma *Release* com os arquivos.

**Manual (Windows):**

```powershell
pip install -r requirements.txt -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File instalador\build.ps1
# reaproveitando um Tesseract já instalado:
powershell -ExecutionPolicy Bypass -File instalador\build.ps1 -TesseractOrigem "C:\Program Files\Tesseract-OCR"
```

Saída em `saida\`. Requer Inno Setup 6 (instalado via Chocolatey se faltar).
Para lançar uma nova versão, altere `versao.py`.

## Segurança

O app instalado atende só `127.0.0.1` (esta máquina). Não exponha a porta 5002
para a internet: o app processa documentos jurídicos e financeiros sigilosos.
