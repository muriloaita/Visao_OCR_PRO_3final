"""
ocr_server.py
=============
Servico de extracao de texto de PDFs (PyMuPDF + Tesseract OCR) para o SysMG.
Recebe um PDF via multipart/form-data, processa pagina a pagina
(texto digital ou OCR com Tesseract) e retorna o texto extraido em JSON.

Adaptado do Visao OCR Pro para rodar em servidor Linux (VPS / Docker):
    - Tesseract localizado pelo PATH (ou pela variavel TESSERACT_CMD)
    - Acesso protegido por token (variavel OCR_API_TOKEN)
    - Prompt mestre do modo extrato lido de arquivo externo (PROMPT_EXTRATO_PATH),
      fora do repositorio
    - Executado com gunicorn (ver Dockerfile)

Rotas:
    GET  /health   -> status do servico (sem token)
    POST /ocr      -> texto extraido + estatisticas
    POST /extrato  -> idem + prompt forense com o texto embutido
"""

import hmac
import os
import shutil
import subprocess

import pymupdf as fitz  # PyMuPDF
import pytesseract
from PIL import Image
from flask import Flask, request, jsonify

# ─────────────────────────────────────────────────────
# CONFIGURACAO (via variaveis de ambiente)
# ─────────────────────────────────────────────────────
TESSERACT_CMD = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
IDIOMA_OCR = os.environ.get("IDIOMA_OCR", "por")  # "por" | "eng" | "por+eng"
DPI_SCAN = int(os.environ.get("DPI_SCAN", "300"))  # resolucao para OCR em paginas escaneadas
LIMITE_CHARS = 50  # minimo de caracteres para considerar pagina como "digital"
OCR_API_TOKEN = os.environ.get("OCR_API_TOKEN", "")
PROMPT_EXTRATO_PATH = os.environ.get(
    "PROMPT_EXTRATO_PATH", "/app/prompts/prompt_mestre_extrato.md"
)
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
PORT = int(os.environ.get("PORT", "5001"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    print(f"[OK] Tesseract: {TESSERACT_CMD}")
else:
    print("AVISO: Tesseract nao encontrado. O OCR para paginas escaneadas falhara.")

if not OCR_API_TOKEN:
    print("AVISO: OCR_API_TOKEN nao definido. As rotas /ocr e /extrato recusarao requisicoes.")


def token_valido() -> bool:
    """Confere o header 'Authorization: Bearer <token>'."""
    if not OCR_API_TOKEN:
        return False
    enviado = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return hmac.compare_digest(enviado.encode(), OCR_API_TOKEN.encode())


@app.before_request
def exigir_token():
    if request.path != "/health" and not token_valido():
        return jsonify({"erro": "Token de acesso ausente ou invalido."}), 401


@app.errorhandler(413)
def arquivo_grande(_e):
    return jsonify({"erro": f"Arquivo acima do limite de {MAX_UPLOAD_MB} MB."}), 413


def extrair_texto_digital(pagina: fitz.Page) -> str:
    """Extrai texto embutido de uma pagina digital."""
    return pagina.get_text().strip()


def extrair_texto_ocr(pagina: fitz.Page) -> str:
    """Converte uma pagina em imagem e aplica OCR com Tesseract."""
    mat = fitz.Matrix(DPI_SCAN / 72, DPI_SCAN / 72)
    pix = pagina.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    texto = pytesseract.image_to_string(img, lang=IDIOMA_OCR, config="--psm 6")
    return texto.strip()


def processar_pdf_bytes(pdf_bytes: bytes) -> dict:
    """
    Processa um PDF a partir de bytes, detectando cada pagina como digital ou escaneada.
    Retorna um dict com o texto completo e estatisticas.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = len(doc)
    resultado = []
    pags_digital = 0
    pags_ocr = 0
    paginas_info = []

    for i, pagina in enumerate(doc):
        num = i + 1
        texto_digital = extrair_texto_digital(pagina)

        if len(texto_digital) >= LIMITE_CHARS:
            pags_digital += 1
            resultado.append(f"=== PAGINA {num} (Digital) ===\n{texto_digital}")
            paginas_info.append(
                {"pagina": num, "tipo": "digital", "chars": len(texto_digital)}
            )
        else:
            pags_ocr += 1
            try:
                texto_ocr = extrair_texto_ocr(pagina)
                resultado.append(f"=== PAGINA {num} (OCR) ===\n{texto_ocr}")
                paginas_info.append(
                    {"pagina": num, "tipo": "ocr", "chars": len(texto_ocr)}
                )
            except Exception as e:
                resultado.append(
                    f"=== PAGINA {num} (OCR - ERRO) ===\n[Erro ao processar: {str(e)}]"
                )
                paginas_info.append({"pagina": num, "tipo": "ocr_erro", "chars": 0})

    doc.close()
    texto_completo = "\n\n".join(resultado)

    return {
        "texto": texto_completo,
        "total_paginas": total,
        "paginas_digitais": pags_digital,
        "paginas_ocr": pags_ocr,
        "paginas": paginas_info,
        "chars_totais": len(texto_completo),
    }


def ler_pdf_enviado():
    """Valida o campo 'file' e devolve (nome, bytes) ou (None, resposta de erro)."""
    if "file" not in request.files:
        return None, (jsonify({"erro": "Nenhum arquivo enviado. Use o campo 'file'."}), 400)

    arquivo = request.files["file"]
    if arquivo.filename == "":
        return None, (jsonify({"erro": "Nome de arquivo vazio."}), 400)

    if not arquivo.filename.lower().endswith(".pdf"):
        return None, (jsonify({"erro": "Apenas arquivos PDF sao aceitos."}), 400)

    return (arquivo.filename, arquivo.read()), None


@app.route("/health", methods=["GET"])
def health():
    """Endpoint de verificacao de saude do servidor."""
    tess_version = "nao encontrado"
    tess_ok = False

    if TESSERACT_CMD:
        try:
            out = subprocess.check_output(
                [TESSERACT_CMD, "--version"],
                stderr=subprocess.STDOUT,
                timeout=5,
            ).decode("utf-8", errors="ignore")
            # Primeira linha: "tesseract vX.Y.Z"
            primeira_linha = out.strip().splitlines()[0] if out.strip() else ""
            tess_version = primeira_linha.replace("tesseract ", "").strip() or "encontrado"
            tess_ok = True
        except Exception:
            tess_version = "erro ao executar"

    return jsonify(
        {
            "status": "online",
            "tesseract_ok": tess_ok,
            "tesseract_versao": tess_version,
            "idioma_padrao": IDIOMA_OCR,
            "dpi": DPI_SCAN,
            "prompt_extrato_ok": os.path.isfile(PROMPT_EXTRATO_PATH),
        }
    )


@app.route("/ocr", methods=["POST"])
def ocr():
    """
    Recebe um arquivo PDF via multipart/form-data (campo 'file')
    e retorna o texto extraido + estatisticas em JSON.
    """
    enviado, erro = ler_pdf_enviado()
    if erro:
        return erro
    nome, pdf_bytes = enviado

    try:
        print(f"[OCR] Processando: {nome} ({len(pdf_bytes)/1024/1024:.2f} MB)")
        resultado = processar_pdf_bytes(pdf_bytes)
        print(
            f"[OCR] Concluido: {resultado['total_paginas']} paginas | "
            f"Digital: {resultado['paginas_digitais']} | OCR: {resultado['paginas_ocr']}"
        )
        return jsonify(resultado)

    except Exception as e:
        print(f"[ERRO] {str(e)}")
        return jsonify({"erro": f"Falha no processamento: {str(e)}"}), 500


# ─────────────────────────────────────────────────────
# MODO EXTRATO FINANCEIRO FORENSE
# O prompt mestre fica em arquivo externo (PROMPT_EXTRATO_PATH), fora do
# repositorio. Marcadores aceitos: {ocr_texto}, {data_inicio}, {data_fim}, {filtro}
# ─────────────────────────────────────────────────────
@app.route("/extrato", methods=["POST"])
def extrato():
    """
    Modo Extrato Financeiro Forense.
    Recebe um PDF + parametros de auditoria e retorna:
      - O resultado OCR padrao (mesmo formato do /ocr)
      - O prompt mestre de auditoria com o texto OCR embutido e pronto para uso em IA
    """
    if not os.path.isfile(PROMPT_EXTRATO_PATH):
        return jsonify({"erro": f"Prompt mestre nao encontrado em {PROMPT_EXTRATO_PATH}."}), 500

    enviado, erro = ler_pdf_enviado()
    if erro:
        return erro
    nome, pdf_bytes = enviado

    # Parametros do periodo e filtro enviados pelo SysMG
    data_inicio = request.form.get("data_inicio", "INÍCIO DO DOCUMENTO")
    data_fim = request.form.get("data_fim", "FIM DO DOCUMENTO")
    filtro = request.form.get("filtro", "TODOS OS LANÇAMENTOS")

    try:
        print(f"[EXTRATO] Processando: {nome} ({len(pdf_bytes)/1024/1024:.2f} MB)")
        resultado = processar_pdf_bytes(pdf_bytes)
        print(
            f"[EXTRATO] Concluido: {resultado['total_paginas']} paginas | "
            f"Digital: {resultado['paginas_digitais']} | OCR: {resultado['paginas_ocr']}"
        )

        # Monta o prompt forense com o texto OCR embutido.
        # replace() em vez de format(): chaves literais no prompt nao quebram a montagem.
        with open(PROMPT_EXTRATO_PATH, encoding="utf-8") as f:
            prompt_forense = f.read()
        for marcador, valor in (
            ("{data_inicio}", data_inicio),
            ("{data_fim}", data_fim),
            ("{filtro}", filtro),
            ("{ocr_texto}", resultado["texto"]),
        ):
            prompt_forense = prompt_forense.replace(marcador, valor)

        return jsonify(
            {
                **resultado,
                "modo_extrato": True,
                "prompt_forense": prompt_forense,
                "parametros": {
                    "data_inicio": data_inicio,
                    "data_fim": data_fim,
                    "filtro": filtro,
                },
            }
        )

    except Exception as e:
        print(f"[ERRO EXTRATO] {str(e)}")
        return jsonify({"erro": f"Falha no processamento do extrato: {str(e)}"}), 500


if __name__ == "__main__":
    # Apenas para teste local; em producao use gunicorn (ver Dockerfile)
    app.run(host="127.0.0.1", port=PORT, debug=False)
