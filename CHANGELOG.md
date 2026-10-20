# Histórico de versões

## 3.0.0 — somente OCR

**Retirado** (era da 2.0):
- Modo *Extrato Financeiro Forense* (`/api/ocr/extrato`, `/extrato/recalcular`,
  `extrato_parser.py`, prompt mestre de auditoria, confirmação de saldo inicial,
  CSV/XLSX de lançamentos).
- Modo *Extrato de Cartão / maquininha* (`/api/ocr/extrato-cartao`,
  `vendas_cartao.py`, CSV/XLSX de vendas Vero/Rede).
- `exportar_dataset_apuracao.py` e as dependências `openpyxl`, `pandas`, `pdfplumber`.
- Servidor Node intermediário (`server.ts`, Express/multer/axios): o Flask serve
  o site e a API na mesma porta.

**Mantido da 2.0** (motor de OCR):
- Detecção digital / escaneada / mista (PROJUDI) por página.
- Filtro de confiança por palavra, limpeza de artefatos, siglas sem vogal, NFC.
- Zoom de renderização pela resolução nativa da imagem embutida.
- Tratamento de fundo escuro/zebrado e mediana adaptativa.
- Forçar OCR, lotes de páginas (`pagina_inicio`/`pagina_fim`), contagem de páginas.
- Tesseract portátil ao lado do executável com prioridade; site em `dist/`.

**Novo:**
- Instalador 3.0 completo (PyInstaller + Inno Setup) com Tesseract 5 e português
  embutidos; instala sem administrador na mesma pasta da 2.0 e remove a versão
  antiga e seus restos automaticamente.
- ZIP portátil (roda sem instalar).
- Ícone na bandeja (Abrir / Processar pasta de PDFs… / Sair) e instância única.
- *Processar pasta de PDFs* (aproveitado do antigo `processar_lote.py`, agora com
  o motor novo): um `_texto.txt` por PDF + `relatorio_lote.txt`.
- `/api/ocr/health` informa a versão do app e se o português está instalado
  (`idioma_ok`); aviso na tela quando faltar.
- Botão Cancelar no processamento em lotes; contagem de páginas com erro.
- Chamadas ao Tesseract sem piscar janela de console no Windows.
- Log do servidor em `%LOCALAPPDATA%\VisaoOCRPro\logs\servidor.log`.
- Testes automatizados (pytest) e build/teste do instalador no GitHub Actions.
- PyMuPDF fixado na linha 1.x (a 2.x exige onnxruntime e um modelo de layout).
