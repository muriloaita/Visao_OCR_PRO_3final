"""
ocr_server.py
=============
Servidor Flask que expoe o Tesseract OCR como uma API REST.
Recebe um PDF via multipart/form-data, processa pagina a pagina
(texto digital ou OCR com Tesseract) e retorna o texto extraido em JSON.

Versao 3 (somente OCR): os modos de extrato bancario e de extrato de
cartao (maquininha) foram retirados do aplicativo.

Dependencias:
    pip install -r requirements.txt

Requisito externo:
    Tesseract instalado em: C:\\Program Files\\Tesseract-OCR\\tesseract.exe
    Download: https://github.com/UB-Mannheim/tesseract/wiki
    (Durante a instalacao, selecione o idioma "Portuguese")
    Na instalacao desktop o Tesseract ja vem embutido (pasta Tesseract-OCR/).

Uso:
    python ocr_server.py
    Acessa em: http://localhost:5002
"""

import os
import io
import re
import sys
import subprocess
import unicodedata

# Forcar UTF-8 no stdout/stderr — necessario no Windows (default e cp1252)
# Evita: 'charmap' codec can't encode character
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24.3
except ImportError:
    import fitz  # PyMuPDF antigo
import pytesseract
from PIL import Image, ImageFilter, ImageOps
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# ─────────────────────────────────────────────────────
# CONFIGURACAO
# ─────────────────────────────────────────────────────

from versao import VERSAO_APP

# No Windows, evita que cada chamada a um executavel externo abra uma
# janela de console (o app desktop roda sem console).
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Diretório-base da aplicação. Quando "congelado" pelo PyInstaller
# (instalador desktop), os recursos (dist/, Tesseract-OCR/) ficam ao lado
# do executável — não ao lado deste .py dentro do bundle.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# Tesseract portátil embutido na instalação desktop (tem prioridade)
TESSERACT_LOCAL = os.path.join(BASE_DIR, "Tesseract-OCR", "tesseract.exe")
IDIOMA_OCR = "por"  # Idioma principal; adicione '+eng' apenas se necessário
DPI_SCAN = 300  # 300 DPI é suficiente para OCR preciso (400 causa lentidão)
CONF_MIN_ANCORA = 55  # confiança mínima (0-100) p/ uma palavra "ancorar" a linha no OCR
MAX_PIXELS_RENDER = 24_000_000  # teto de pixels ao renderizar página (protege a memória)
LIMITE_CHARS = 50  # minimo de caracteres para considerar pagina como "digital"

# Detecção de páginas mistas: se uma página tem texto digital + imagem embutida grande
# (típico de PDFs judiciais como PROJUDI), a imagem é o documento escaneado real.
IMG_MISTA_MIN_PX = 500   # dimensão mínima (largura e altura) para considerar imagem como documento
IMG_MISTA_MIN_AREA = 250_000  # área mínima em pixels (ex: 500x500 = 250.000)
PORT = 5002

# Pasta do site pronto (gerado por `npm run build`). Servido pelo próprio Flask
# em produção — assim o servidor precisa apenas de Python + Tesseract (sem Node).
DIST_DIR = os.path.join(BASE_DIR, "dist")

app = Flask(__name__, static_folder=None)
CORS(app)  # Permite requisicoes do frontend em desenvolvimento (Vite em outra porta)


# Configura o Tesseract imediatamente na inicializacao do modulo
# (antes de qualquer endpoint ser chamado)
def configurar_tesseract():
    """Verifica e configura o caminho do Tesseract."""
    import shutil

    # Prioridade: Tesseract portátil ao lado do app (instalação desktop),
    # depois o caminho padrão do Windows, depois o PATH.
    caminho = None
    if os.path.exists(TESSERACT_LOCAL):
        caminho = TESSERACT_LOCAL
    elif os.path.exists(TESSERACT_CMD):
        caminho = TESSERACT_CMD

    if caminho:
        pytesseract.pytesseract.tesseract_cmd = caminho
        # Garante que o diretório do Tesseract está no PATH do processo
        # (necessário para o Flask encontrar as DLLs via subprocess)
        tess_dir = os.path.dirname(caminho)
        if tess_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = tess_dir + os.pathsep + os.environ.get("PATH", "")
        # O Tesseract embutido usa sempre os idiomas da propria pasta, mesmo
        # que a maquina tenha um TESSDATA_PREFIX apontando para outro lugar.
        if caminho == TESSERACT_LOCAL:
            os.environ["TESSDATA_PREFIX"] = os.path.join(tess_dir, "tessdata")
        print(f"[OK] Tesseract encontrado: {caminho}")
    else:
        tess_in_path = shutil.which("tesseract")
        if tess_in_path:
            pytesseract.pytesseract.tesseract_cmd = tess_in_path
            print(f"[OK] Tesseract encontrado no PATH: {tess_in_path}")
        else:
            print(
                "AVISO: Tesseract nao encontrado. O OCR para paginas escaneadas falhara."
            )
            print(f"  Caminho esperado: {TESSERACT_CMD}")
            print("  Baixe em: https://github.com/UB-Mannheim/tesseract/wiki")


configurar_tesseract()  # ← executa na importação do modulo


def normalizar_unicode(texto: str) -> str:
    """
    Normaliza o texto para a forma composta (NFC).

    Alguns PDFs trazem os acentos como caracteres SEPARADOS (forma NFD:
    'e' + U+0301), o que aparece para o usuário como "peri´cia" / "e´" ao
    copiar, exportar ou abrir no Excel. O NFC junta cada letra + acento no
    caractere único correto ("perícia", "é").
    """
    return unicodedata.normalize("NFC", texto)


def extrair_texto_digital(pagina: fitz.Page) -> str:
    """Extrai texto embutido de uma pagina digital."""
    return normalizar_unicode(pagina.get_text().strip())


def preprocessar_imagem(img: Image.Image) -> Image.Image:
    """
    Pipeline de pre-processamento para melhorar a precisao do OCR.
    Trata documentos com fundo escuro/zebrado (ex: extrato Bradesco) invertendo
    a imagem quando necessario, antes de binarizar.
    Tenta usar OpenCV (melhor qualidade), com fallback para PIL puro.
    """
    try:
        import cv2
        import numpy as np

        # Converter PIL -> numpy array em escala de cinza
        img_gray = img.convert("L")
        img_np = np.array(img_gray)

        # (CLAHE removido: benchmark em documentos reais — extrato BB
        #  fotografado, processos PROJUDI escaneados — mostrou que o realce
        #  de contraste amplifica ruido de fundo e PIORA o OCR; sem ele os
        #  valores monetarios reconhecidos dobraram no extrato BB.)

        # 1. Detectar se o documento tem fundo predominantemente escuro
        #    (documentos com linhas zebradas escuras tem mediana baixa)
        mediana = np.median(img_np)
        if mediana < 128:
            # Fundo escuro: inverter para que o texto fique preto sobre fundo branco
            img_np = cv2.bitwise_not(img_np)

        # 2. Binarizacao adaptativa (Otsu) — separa texto do fundo automaticamente
        _, img_np = cv2.threshold(img_np, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 3. Remocao de ruido com filtro mediano (remove pontos isolados).
        #    Em imagens grandes usa kernel 5: essencial para "derreter" fundo
        #    reticulado/pontilhado de linhas zebradas (ex: extrato BB impresso),
        #    que de outra forma vira ruido e corrompe o OCR das linhas sombreadas.
        kernel_mediana = 5 if min(img_np.shape[:2]) >= 1500 else 3
        img_np = cv2.medianBlur(img_np, kernel_mediana)

        # Converter de volta para PIL
        return Image.fromarray(img_np)

    except ImportError:
        # Fallback: usar apenas PIL (sem OpenCV)
        print("[AVISO] OpenCV nao instalado. Usando pre-processamento basico com PIL.")
        print("  Para melhor precisao, instale: pip install opencv-python-headless")

        # 1. Escala de cinza
        img_gray = img.convert("L")

        # 2. Aumentar contraste com autocontraste
        img_gray = ImageOps.autocontrast(img_gray, cutoff=1)

        # 3. Detectar fundo escuro pela mediana dos pixels
        import statistics
        pixels = list(img_gray.tobytes())
        mediana = statistics.median(pixels)
        if mediana < 128:
            img_gray = ImageOps.invert(img_gray)

        # 4. Binarizacao com limiar fixo
        threshold = 140
        img_bin = img_gray.point(lambda p: 255 if p > threshold else 0, "1")

        # 5. Leve suavizacao para remover ruido
        img_bin = img_bin.convert("L").filter(ImageFilter.MedianFilter(size=3))

        return img_bin



def ocr_com_filtro_confianca(img: Image.Image) -> str:
    """
    Executa o OCR usando image_to_data (palavra a palavra, com nivel de
    confianca) em vez de image_to_string, e descarta linhas que nao possuem
    nenhuma palavra "ancora".

    Motivo: documentos judiciais (PROJUDI) tem texto de certificacao girado
    90 graus na margem direita e bordas ornamentadas (ex: Junta Comercial).
    O Tesseract le esses trechos como "salada" de caracteres soltos
    (ex: "O CÊ [ou e) Ko) Ee > o ota Su"). Paginas de verso em branco viram
    paginas inteiras de lixo.

    Uma "ancora" e uma palavra confiavel de verdade:
      - 3+ letras com confianca >= CONF_MIN_ANCORA (palavras reais), ou
      - 4+ caracteres alfanumericos com confianca >= CONF_MIN_ANCORA
        (datas, valores, CNPJ, numeros de processo).
    Linha sem nenhuma ancora = ruido -> descartada.
    Tokens de borda sem NENHUMA letra/numero (ex: '|', '=', ')') e com
    confianca baixa tambem sao aparados das pontas da linha.
    """
    data = pytesseract.image_to_data(
        img, lang=IDIOMA_OCR, config="--psm 6", output_type=pytesseract.Output.DICT
    )

    # Agrupar palavras por linha fisica (bloco, paragrafo, linha)
    linhas: dict = {}
    for i in range(len(data["text"])):
        palavra = data["text"][i].strip()
        try:
            conf = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            conf = -1
        if not palavra or conf < 0:
            continue
        chave = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        linhas.setdefault(chave, []).append((conf, palavra))

    def e_ancora(conf: int, palavra: str) -> bool:
        if conf < CONF_MIN_ANCORA:
            return False
        alfa = re.sub(r"[^a-zA-ZÀ-ÿ]", "", palavra)
        if len(alfa) >= 3:
            return True
        alnum = re.sub(r"[^a-zA-Z0-9À-ÿ]", "", palavra)
        return len(alnum) >= 4

    saida = []
    for chave in sorted(linhas):
        pares = linhas[chave]
        if not any(e_ancora(c, p) for c, p in pares):
            continue  # linha sem nenhuma palavra confiavel -> ruido

        # Aparar das pontas tokens de pura pontuacao com confianca baixa.
        # NUNCA remove tokens com letra/numero (preserva 'D'/'C' de extratos).
        def token_borda_lixo(conf: int, palavra: str) -> bool:
            sem_pontuacao = re.sub(r"[^a-zA-Z0-9À-ÿ]", "", palavra)
            return sem_pontuacao == "" and conf < 60

        while pares and token_borda_lixo(*pares[0]):
            pares = pares[1:]
        while pares and token_borda_lixo(*pares[-1]):
            pares = pares[:-1]
        if pares:
            saida.append(" ".join(p for _, p in pares))

    return "\n".join(saida)


def _zoom_render(pagina: fitz.Page) -> float:
    """
    Calcula o zoom de renderização da página para OCR.

    Base: DPI_SCAN (300 dpi). PORÉM, alguns PDFs têm página pequena (ex: foto
    de extrato numa página de 241x170 pt) contendo uma imagem escaneada de
    alta resolução (ex: 3504x2480 px). Renderizar a 300 dpi ENCOLHE essa
    imagem e destrói a qualidade do OCR. Nesses casos, aumenta o zoom até a
    resolução nativa da maior imagem embutida (limitado a MAX_PIXELS_RENDER).
    """
    zoom = DPI_SCAN / 72.0
    try:
        rect = pagina.rect
        if rect.width <= 0 or rect.height <= 0:
            return zoom
        px_por_ponto = 0.0
        for img in pagina.get_images(full=True):
            w, h = img[2], img[3]  # dimensões nativas da imagem embutida
            px_por_ponto = max(px_por_ponto, w / rect.width, h / rect.height)
        if px_por_ponto > zoom:
            zoom = px_por_ponto
        # Teto de segurança: não renderizar acima de MAX_PIXELS_RENDER
        max_zoom = (MAX_PIXELS_RENDER / (rect.width * rect.height)) ** 0.5
        if zoom > max_zoom:
            zoom = max_zoom
    except Exception:
        zoom = DPI_SCAN / 72.0
    return max(zoom, 1.0)


def extrair_texto_ocr(pagina: fitz.Page) -> str:
    """Converte uma pagina em imagem, aplica pre-processamento e OCR com Tesseract."""
    zoom = _zoom_render(pagina)
    mat = fitz.Matrix(zoom, zoom)
    pix = pagina.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    # Pre-processar imagem para melhorar a precisao do OCR
    img = preprocessar_imagem(img)

    texto = ocr_com_filtro_confianca(img)
    return limpar_texto_ocr(texto.strip())


def limpar_texto_ocr(texto: str) -> str:
    """
    Remove artefatos típicos de OCR em documentos escaneados:
      - Tokens sem vogais com 4+ caracteres (sequencias de consoantes aleatorias)
      - Tokens muito longos com poucas vogais (bordas, ornamentos, marcas d'agua)
      - Padroes hex/codigo de assinaturas digitais vazadas (ex: esxsseesxceeesx002)
      - Linhas onde a MAIORIA dos tokens sao lixo

    CONSERVADOR: prefere manter texto duvidoso a remover texto valido.
    So remove quando a evidencia de lixo for clara.
    """
    # NFC primeiro: junta acentos decompostos ("peri" + ´ + "cia" -> "perícia"),
    # senao as heuristicas abaixo veem o acento como caractere solto
    texto = normalizar_unicode(texto)

    # Cobertura completa de vogais portuguesas
    VOGAIS_PT = frozenset('aeiouáàãâéêíóôõúüAEIOUÁÀÃÂÉÊÍÓÔÕÚÜ')

    # Siglas reais SEM vogal, comuns em documentos juridicos/bancarios.
    # Sem esta lista, a regra "4+ letras sem vogal = lixo" apagava CNPJ,
    # FGTS, SSP/PR etc. do texto entregue.
    SIGLAS_SEM_VOGAL = frozenset({
        'CNPJ', 'FGTS', 'CTPS', 'CLT', 'CDC', 'CPC', 'CTN', 'CTB',
        'SSP', 'SSPPR', 'SSPSP', 'SSPMG', 'SSPRS', 'SSPSC', 'SSPRJ',
        'TJPR', 'TJSP', 'TJMG', 'TJRS', 'TJSC', 'TJRJ', 'TJMS', 'TJMT',
        'TRT', 'TST', 'STF', 'STJ', 'CNJ', 'CNH', 'SPC', 'PMPR', 'DHPP',
    })

    def token_e_lixo(token: str) -> bool:
        """Retorna True se o token parece ser um artefato OCR."""
        # Remove pontuacao para analise
        apenas_alfa = re.sub(r'[^a-zA-ZÀ-ÿ]', '', token)

        if len(apenas_alfa) <= 3:
            return False  # Tokens curtos: manter (maioria valida)

        num_vogais = sum(1 for c in apenas_alfa if c in VOGAIS_PT)
        comprimento = len(apenas_alfa)
        proporcao_vogais = num_vogais / comprimento

        # Regra 1: token com 4+ chars e NENHUMA vogal -> lixo,
        # EXCETO siglas conhecidas (CNPJ, FGTS, SSP/PR, TJPR...)
        if num_vogais == 0 and comprimento >= 4:
            if apenas_alfa.upper() in SIGLAS_SEM_VOGAL:
                return False
            return True

        # Regra 2: token longo (20+ chars) com muito pouca vogal (<12%) -> lixo
        # Ex: 'ESTLLALRESESTIALLLTESTESCAETESTELAS'
        if comprimento >= 20 and proporcao_vogais < 0.12:
            return True

        # Regra 3: token muito longo (30+ chars) -> altamente suspeito
        if comprimento >= 30 and proporcao_vogais < 0.20:
            return True

        # Regra 4: padrao hex/codigo (ex: esxsseesxceeesx002, x002)
        apenas_alnum = re.sub(r'[^a-zA-Z0-9]', '', token)
        if len(apenas_alnum) >= 6:
            # Hex puro: exige AO MENOS UM digito, senao palavras reais
            # so com letras a-f seriam apagadas (ex: 'facada', 'decada')
            if (re.match(r'^[a-f0-9]+$', apenas_alnum, re.IGNORECASE)
                    and re.search(r'[0-9]', apenas_alnum)):
                return True  # hex puro
            if re.match(r'^[a-z]{2,}[0-9]{3,}', apenas_alnum, re.IGNORECASE):
                return True  # letras seguidas de muitos numeros

        return False

    linhas = texto.split('\n')
    linhas_limpas = []

    for linha in linhas:
        # Preservar linhas vazias (estrutura do documento)
        if not linha.strip():
            linhas_limpas.append('')
            continue

        tokens = linha.split()
        if not tokens:
            linhas_limpas.append('')
            continue

        tokens_ok = [t for t in tokens if not token_e_lixo(t)]
        tokens_lixo = len(tokens) - len(tokens_ok)

        # Se mais de 70% da linha sao lixo E a linha tem 4+ tokens -> descartar linha
        if len(tokens) >= 4 and tokens_lixo / len(tokens) > 0.70:
            continue

        # Se pelo menos algum token sobrou, usar a linha limpa
        if tokens_ok:
            linhas_limpas.append(' '.join(tokens_ok))
        # Linha onde TODOS os tokens foram removidos: descartar silenciosamente

    # Colapsar multiplas linhas vazias consecutivas em no maximo uma
    resultado = re.sub(r'\n{3,}', '\n\n', '\n'.join(linhas_limpas))
    return resultado.strip()


def detectar_imagens_documento(doc: fitz.Document, pagina: fitz.Page) -> list:
    """
    Detecta imagens embutidas grandes na página que representam documentos escaneados.
    Retorna lista de xrefs de imagens que atendem ao critério de "documento escaneado".
    Filtros:
      - Dimensão mínima: >= IMG_MISTA_MIN_PX em ambos os lados
      - Área mínima: >= IMG_MISTA_MIN_AREA pixels
      - Prioridade: imagens grayscale (cs=1) típicas de documentos escaneados
    """
    imgs_documento = []
    for img in pagina.get_images(full=True):
        xref = img[0]
        try:
            info = doc.extract_image(xref)
            w = info["width"]
            h = info["height"]
            area = w * h
            if w >= IMG_MISTA_MIN_PX and h >= IMG_MISTA_MIN_PX and area >= IMG_MISTA_MIN_AREA:
                imgs_documento.append({
                    "xref": xref,
                    "width": w,
                    "height": h,
                    "colorspace": info.get("colorspace", -1),
                    "ext": info["ext"],
                    "image_bytes": info["image"],
                })
        except Exception:
            pass
    return imgs_documento


def ocr_imagem_bytes(img_bytes: bytes, ext: str) -> str:
    """
    Aplica OCR diretamente nos bytes de uma imagem embutida no PDF.
    Usa o mesmo pipeline de pre-processamento da pagina completa.
    """
    img = Image.open(io.BytesIO(img_bytes))
    # Converter para RGB se necessario (grayscale, CMYK, etc.)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img = preprocessar_imagem(img)
    texto = ocr_com_filtro_confianca(img)
    return limpar_texto_ocr(texto.strip())


def processar_pdf_bytes(
    pdf_bytes: bytes,
    forcar_ocr: bool = False,
    callback=None,
    pagina_inicio: int = None,
    pagina_fim: int = None,
) -> dict:
    """
    Processa um PDF a partir de bytes, detectando cada página como:
      - Digital pura: só texto embutido, sem imagens de documento
      - OCR pura: sem texto digital, imagem escaneada
      - Mista: texto digital (ex: rodapé judicial PROJUDI) + imagem escaneada embutida
              -> faz OCR na imagem embutida e concatena com texto do rodapé

    Parâmetros:
        forcar_ocr: Se True, renderiza TODAS as páginas como imagem e passa pelo Tesseract.
                    Garante que mesmo páginas com texto digital sejam totalmente relidas pelo OCR.
        pagina_inicio / pagina_fim: intervalo 1-indexado INCLUSIVO a processar.
                    Usado para dividir PDFs extensos em lotes. Fora do intervalo,
                    a página é ignorada (mas numeração e total permanecem globais).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = len(doc)
    resultado = []
    pags_digital = 0
    pags_ocr = 0
    pags_mistas = 0
    paginas_info = []

    for i, pagina in enumerate(doc):
        num = i + 1

        # Fora do lote solicitado: pula sem renderizar (evita custo de OCR)
        if pagina_inicio is not None and num < pagina_inicio:
            continue
        if pagina_fim is not None and num > pagina_fim:
            break

        if forcar_ocr:
            # ── MODO FORÇAR OCR: renderiza a página inteira pelo PyMuPDF e passa ao Tesseract ──
            # Captura tudo: texto digital, imagens embutidas, gráficos, rodapés
            pags_ocr += 1
            try:
                texto_ocr = extrair_texto_ocr(pagina)
                resultado.append(f"=== PAGINA {num} (OCR Forçado) ===\n{texto_ocr}")
                paginas_info.append(
                    {"pagina": num, "tipo": "ocr_forcado", "chars": len(texto_ocr)}
                )
            except Exception as e:
                resultado.append(
                    f"=== PAGINA {num} (OCR - ERRO) ===\n[Erro ao processar: {str(e)}]"
                )
                paginas_info.append({"pagina": num, "tipo": "ocr_erro", "chars": 0})

        else:
            # ── MODO AUTOMÁTICO: detecta tipo da página ──
            texto_digital = extrair_texto_digital(pagina)
            imgs_doc = detectar_imagens_documento(doc, pagina)

            tem_texto_suficiente = len(texto_digital) >= LIMITE_CHARS
            tem_imagem_documento = len(imgs_doc) > 0

            if tem_texto_suficiente and tem_imagem_documento:
                # ── PÁGINA MISTA: rodapé digital + imagem escaneada (típico PROJUDI) ──
                # Faz OCR em cada imagem de documento embutida e concatena resultados
                pags_mistas += 1
                textos_imagens = []
                for img_info in imgs_doc:
                    try:
                        t = ocr_imagem_bytes(img_info["image_bytes"], img_info["ext"])
                        if t:
                            textos_imagens.append(t)
                    except Exception as e:
                        textos_imagens.append(f"[Erro OCR imagem: {str(e)}]")

                texto_final = "\n\n".join(textos_imagens)
                # Inclui o texto do rodapé apenas se não é puramente navegacional
                # (heurística: rodapé do PROJUDI é menor que 600 chars)
                if texto_digital and len(texto_digital) < 600:
                    texto_final = texto_final + f"\n\n[Rodapé Digital]: {texto_digital}"

                resultado.append(f"=== PAGINA {num} (Mista: OCR+Digital) ===\n{texto_final}")
                paginas_info.append(
                    {"pagina": num, "tipo": "mista", "chars": len(texto_final),
                     "imagens_ocr": len(imgs_doc)}
                )

            elif tem_texto_suficiente:
                # ── PÁGINA DIGITAL PURA: sem imagens de documento ──
                pags_digital += 1
                resultado.append(f"=== PAGINA {num} (Digital) ===\n{texto_digital}")
                paginas_info.append(
                    {"pagina": num, "tipo": "digital", "chars": len(texto_digital)}
                )

            else:
                # ── PÁGINA OCR: sem texto digital suficiente, renderiza e aplica Tesseract ──
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
        "paginas_mistas": pags_mistas,
        "forcar_ocr": forcar_ocr,
        "paginas": paginas_info,
        "chars_totais": len(texto_completo),
    }


def listar_idiomas_tesseract(caminho_tess: str) -> list:
    """Idiomas instalados no Tesseract (ex: ['eng', 'osd', 'por'])."""
    try:
        out = subprocess.check_output(
            [caminho_tess, "--list-langs"],
            stderr=subprocess.STDOUT,
            timeout=5,
            creationflags=SEM_JANELA,
        ).decode("utf-8", errors="ignore")
    except Exception:
        return []
    # A primeira linha e o cabecalho 'List of available languages ...'
    return sorted(
        linha.strip()
        for linha in out.splitlines()[1:]
        if re.fullmatch(r"[A-Za-z0-9_]+", linha.strip())
    )


@app.route("/health", methods=["GET"])
@app.route("/api/ocr/health", methods=["GET"])
def health():
    """Endpoint de verificacao de saude do servidor."""
    import shutil

    # Usa o caminho efetivamente configurado (portátil local, Program Files
    # ou PATH), e não apenas o caminho fixo TESSERACT_CMD.
    caminho_tess = pytesseract.pytesseract.tesseract_cmd
    exe_existe = os.path.exists(caminho_tess) or bool(shutil.which(caminho_tess))
    tess_version = "nao encontrado"
    tess_ok = False
    idiomas = []

    if exe_existe:
        tess_ok = True  # executável presente = OCR funcional
        try:
            # Chama diretamente via subprocess (imune a problemas de PATH do pytesseract)
            out = subprocess.check_output(
                [caminho_tess, "--version"],
                stderr=subprocess.STDOUT,
                timeout=5,
                creationflags=SEM_JANELA,
            ).decode("utf-8", errors="ignore")
            # Primeira linha: "tesseract vX.Y.Z"
            primeira_linha = out.strip().splitlines()[0] if out.strip() else ""
            tess_version = (
                primeira_linha.replace("tesseract ", "").strip() or "encontrado"
            )
        except Exception:
            tess_version = "instalado"  # existe mas não conseguiu ler versão
        idiomas = listar_idiomas_tesseract(caminho_tess)

    return jsonify(
        {
            "status": "online",
            "versao_app": VERSAO_APP,
            "tesseract_ok": tess_ok,
            "tesseract_versao": tess_version,
            "idioma_padrao": IDIOMA_OCR,
            # False quando o Tesseract existe mas falta o português (por.traineddata)
            "idioma_ok": IDIOMA_OCR in idiomas if idiomas else tess_ok,
            "idiomas": idiomas,
            "dpi": DPI_SCAN,
        }
    )


def _int_form(campo: str):
    """Lê um inteiro do form-data; retorna None se ausente ou inválido."""
    valor = request.form.get(campo)
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (ValueError, TypeError):
        return None


@app.route("/pdf/paginas", methods=["POST"])
@app.route("/api/ocr/paginas", methods=["POST"])
def pdf_paginas():
    """Retorna apenas a contagem de páginas do PDF (rápido, sem OCR)."""
    if "file" not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado. Use o campo 'file'."}), 400
    arquivo = request.files["file"]
    if not arquivo.filename.lower().endswith(".pdf"):
        return jsonify({"erro": "Apenas arquivos PDF sao aceitos."}), 400
    try:
        doc = fitz.open(stream=arquivo.read(), filetype="pdf")
        total = len(doc)
        doc.close()
        return jsonify({"total_paginas": total})
    except Exception as e:
        return jsonify({"erro": f"Falha ao ler o PDF: {str(e)}"}), 500


@app.route("/ocr", methods=["POST"])
@app.route("/api/ocr/processar", methods=["POST"])
def ocr():
    """
    Recebe um arquivo PDF via multipart/form-data (campo 'file')
    e retorna o texto extraido + estatisticas em JSON.
    """
    if "file" not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado. Use o campo 'file'."}), 400

    arquivo = request.files["file"]
    if arquivo.filename == "":
        return jsonify({"erro": "Nome de arquivo vazio."}), 400

    if not arquivo.filename.lower().endswith(".pdf"):
        return jsonify({"erro": "Apenas arquivos PDF sao aceitos."}), 400

    # Lê o parâmetro forcar_ocr (enviado como string "true"/"false" no form-data)
    forcar_ocr = request.form.get("forcar_ocr", "false").lower() == "true"
    pagina_inicio = _int_form("pagina_inicio")
    pagina_fim = _int_form("pagina_fim")

    try:
        pdf_bytes = arquivo.read()
        modo_log = "OCR FORÇADO" if forcar_ocr else "Automático"
        faixa_log = (
            f" | Lote: pág {pagina_inicio}-{pagina_fim}"
            if pagina_inicio or pagina_fim
            else ""
        )
        print(
            f"[OCR] Processando: {arquivo.filename} ({len(pdf_bytes)/1024/1024:.2f} MB) | Modo: {modo_log}{faixa_log}"
        )
        resultado = processar_pdf_bytes(
            pdf_bytes,
            forcar_ocr=forcar_ocr,
            pagina_inicio=pagina_inicio,
            pagina_fim=pagina_fim,
        )
        print(
            f"[OCR] Concluido: {resultado['total_paginas']} paginas | "
            f"Digital: {resultado['paginas_digitais']} | OCR: {resultado['paginas_ocr']} | Forçado: {forcar_ocr}"
        )
        return jsonify(resultado)

    except Exception as e:
        print(f"[ERRO] {str(e)}")
        return jsonify({"erro": f"Falha no processamento: {str(e)}"}), 500


# ─────────────────────────────────────────────────────
# SITE (FRONTEND) — servido pelo próprio Flask em produção
# ─────────────────────────────────────────────────────
# Serve os arquivos gerados por `npm run build` (pasta dist/). Assim o servidor
# de produção precisa apenas de Python + Tesseract, sem Node.js. Em
# desenvolvimento continue usando o Vite (npm run dev:frontend).


@app.route("/", defaults={"filename": ""})
@app.route("/<path:filename>")
def servir_site(filename):
    """Serve o site pronto (SPA). Arquivos inexistentes caem no index.html."""
    # Nunca sequestrar as rotas de API
    if filename.startswith(("api/", "pdf/")) or filename in ("health", "ocr"):
        return jsonify({"erro": "Rota não encontrada."}), 404

    if not os.path.isdir(DIST_DIR):
        return (
            "<h1>Visão OCR Pro</h1><p>O site ainda não foi compilado. "
            "Rode <code>npm run build</code> para gerar a pasta <code>dist/</code>.</p>",
            200,
        )

    alvo = os.path.join(DIST_DIR, filename)
    if filename and os.path.isfile(alvo):
        return send_from_directory(DIST_DIR, filename)
    # SPA: qualquer outra rota devolve o index.html
    return send_from_directory(DIST_DIR, "index.html")


if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  VISAO OCR PRO - Servidor Tesseract")
    print("=" * 55)
    configurar_tesseract()
    tem_site = os.path.isdir(DIST_DIR)
    print(f"\n[INFO] Servidor de desenvolvimento na porta {PORT}...")
    print(f"[INFO] Saude:  http://localhost:{PORT}/api/ocr/health")
    if tem_site:
        print(f"[INFO] Site:   http://localhost:{PORT}/")
    else:
        print("[INFO] Site nao compilado (rode 'npm run build' para servir o site aqui).")
    print("[INFO] Em PRODUCAO use o waitress (multiusuario):")
    print(f"       waitress-serve --host=0.0.0.0 --port={PORT} ocr_server:app")
    print("=" * 55 + "\n")
    # app.run() e o servidor de DESENVOLVIMENTO (1 requisicao por vez).
    # Para producao multiusuario, use o waitress (ver linha acima).
    app.run(host="0.0.0.0", port=PORT, debug=False)
