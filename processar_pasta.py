"""
processar_pasta.py
==================
Processa todos os PDFs de uma pasta com o mesmo motor do Visão OCR Pro
(texto digital, OCR do Tesseract e páginas mistas do PROJUDI).

Gera, ao lado de cada PDF, um arquivo <nome>_texto.txt e, na pasta, um
relatorio_lote.txt com o resumo. PDFs que já têm o _texto.txt são pulados
(use --refazer para processar de novo).

Uso:
    python processar_pasta.py "C:\\caminho\\da\\pasta"
    python processar_pasta.py "C:\\caminho\\da\\pasta" --forcar-ocr --refazer

Na versão instalada: ícone da bandeja > "Processar pasta de PDFs...".
"""

import argparse
import os
import sys
import time

SUFIXO_SAIDA = "_texto.txt"
NOME_RELATORIO = "relatorio_lote.txt"


def caminho_saida(pdf_path: str) -> str:
    return os.path.splitext(pdf_path)[0] + SUFIXO_SAIDA


def listar_pdfs(pasta: str, refazer: bool = False) -> list:
    """PDFs da pasta (sem subpastas), em ordem alfabética."""
    pdfs = []
    for nome in sorted(os.listdir(pasta), key=str.lower):
        caminho = os.path.join(pasta, nome)
        if not (os.path.isfile(caminho) and nome.lower().endswith(".pdf")):
            continue
        if not refazer and os.path.exists(caminho_saida(caminho)):
            continue
        pdfs.append(caminho)
    return pdfs


def processar_arquivo(pdf_path: str, forcar_ocr: bool = False) -> dict:
    """Faz o OCR de um PDF e grava o _texto.txt. Devolve as estatísticas."""
    from ocr_server import processar_pdf_bytes

    with open(pdf_path, "rb") as f:
        resultado = processar_pdf_bytes(f.read(), forcar_ocr=forcar_ocr)
    with open(caminho_saida(pdf_path), "w", encoding="utf-8") as f:
        f.write(resultado["texto"])
    return resultado


def processar_lista(pdfs: list, forcar_ocr: bool = False, progresso=None) -> dict:
    """
    Processa a lista de PDFs e grava o relatório na pasta do primeiro arquivo.
    progresso(indice, total, nome) é chamado antes de cada arquivo.
    """
    linhas = []
    ok = erros = 0
    inicio_total = time.time()

    for indice, pdf_path in enumerate(pdfs, 1):
        nome = os.path.basename(pdf_path)
        if progresso:
            progresso(indice, len(pdfs), nome)
        inicio = time.time()
        try:
            r = processar_arquivo(pdf_path, forcar_ocr=forcar_ocr)
            duracao = time.time() - inicio
            ok += 1
            linhas.append(
                f"{nome} | {r['total_paginas']} págs | {r['paginas_digitais']} digitais | "
                f"{r['paginas_ocr']} OCR | {r.get('paginas_mistas', 0)} mistas | "
                f"{duracao:.1f}s | OK | {os.path.basename(caminho_saida(pdf_path))}"
            )
        except Exception as e:
            erros += 1
            linhas.append(f"{nome} | ERRO: {e}")

    duracao_total = time.time() - inicio_total
    pasta = os.path.dirname(pdfs[0]) if pdfs else os.getcwd()
    relatorio = os.path.join(pasta, NOME_RELATORIO)
    with open(relatorio, "w", encoding="utf-8") as f:
        f.write("RELATÓRIO DE PROCESSAMENTO EM LOTE — VISÃO OCR PRO\n")
        f.write(f"Data: {time.strftime('%d/%m/%Y %H:%M')}\n")
        f.write(f"Modo: {'OCR forçado' if forcar_ocr else 'Automático'}\n")
        f.write("=" * 60 + "\n\n")
        for linha in linhas:
            f.write(linha + "\n")
        f.write(f"\nProcessados: {ok} | Com erro: {erros}\n")
        f.write(f"Tempo total: {duracao_total / 60:.1f} minutos\n")

    return {"ok": ok, "erros": erros, "relatorio": relatorio, "linhas": linhas}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR de todos os PDFs de uma pasta (gera um _texto.txt por PDF)."
    )
    parser.add_argument("pasta", help="pasta com os arquivos PDF")
    parser.add_argument("--forcar-ocr", action="store_true",
                        help="passa todas as páginas pelo Tesseract")
    parser.add_argument("--refazer", action="store_true",
                        help="processa também os PDFs que já têm _texto.txt")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.pasta):
        print(f"ERRO: pasta não encontrada: {args.pasta}")
        return 1

    pdfs = listar_pdfs(args.pasta, refazer=args.refazer)
    if not pdfs:
        print("Nenhum PDF pendente nesta pasta.")
        return 0

    print(f"\n{'=' * 60}\n  PROCESSAMENTO EM LOTE — {len(pdfs)} PDF(s)\n  {args.pasta}\n{'=' * 60}")

    def progresso(indice, total, nome):
        print(f"[{indice}/{total}] {nome}", flush=True)

    resumo = processar_lista(pdfs, forcar_ocr=args.forcar_ocr, progresso=progresso)
    print(f"\nConcluído: {resumo['ok']} OK, {resumo['erros']} com erro.")
    print(f"Relatório: {resumo['relatorio']}")
    return 0 if resumo["erros"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
