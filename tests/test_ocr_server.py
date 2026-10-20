"""
Testes do servidor OCR (somente OCR).

    python -m pytest -q

Os testes de reconhecimento precisam do Tesseract com o idioma português;
sem ele, são pulados.
"""

import io
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ocr_server  # noqa: E402
import processar_pasta  # noqa: E402
from ocr_server import app, fitz  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

TEXTO_DIGITAL = (
    "Contrato de prestação de serviços advocatícios firmado entre as partes, "
    "com vigência de doze meses e foro da comarca de Cianorte."
)
LINHAS_ESCANEADAS = ["PROCURACAO AD JUDICIA", "OUTORGANTE MARIA DA SILVA", "CIANORTE PARANA"]

FONTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def _tem_tesseract_por() -> bool:
    caminho = ocr_server.pytesseract.pytesseract.tesseract_cmd
    if not (os.path.exists(caminho) or shutil.which(caminho)):
        return False
    return "por" in ocr_server.listar_idiomas_tesseract(caminho)


precisa_tesseract = pytest.mark.skipif(
    not _tem_tesseract_por(), reason="Tesseract com idioma 'por' não disponível"
)


def _fonte(tamanho: int):
    for caminho in FONTES:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    pytest.skip("nenhuma fonte TrueType disponível para gerar a imagem de teste")


def pdf_digital(paginas: int = 1) -> bytes:
    doc = fitz.open()
    for n in range(1, paginas + 1):
        pagina = doc.new_page()
        pagina.insert_text((72, 72), f"Pagina numero {n}", fontsize=12)
        pagina.insert_textbox(fitz.Rect(72, 90, 520, 300), TEXTO_DIGITAL, fontsize=11)
    dados = doc.tobytes()
    doc.close()
    return dados


def pdf_escaneado() -> bytes:
    """Página só com imagem (como um documento escaneado)."""
    img = Image.new("RGB", (1700, 900), "white")
    desenho = ImageDraw.Draw(img)
    fonte = _fonte(64)
    for i, linha in enumerate(LINHAS_ESCANEADAS):
        desenho.text((100, 120 + i * 180), linha, fill="black", font=fonte)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = fitz.open()
    pagina = doc.new_page(width=612, height=324)
    pagina.insert_image(pagina.rect, stream=buf.getvalue())
    dados = doc.tobytes()
    doc.close()
    return dados


@pytest.fixture()
def cliente():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def enviar(cliente, dados: bytes, nome="doc.pdf", rota="/api/ocr/processar", **campos):
    form = {"file": (io.BytesIO(dados), nome)}
    form.update({k: str(v) for k, v in campos.items()})
    return cliente.post(rota, data=form, content_type="multipart/form-data")


def test_health(cliente):
    r = cliente.get("/api/ocr/health")
    assert r.status_code == 200
    dados = r.get_json()
    assert dados["status"] == "online"
    assert dados["versao_app"] == ocr_server.VERSAO_APP
    assert dados["idioma_padrao"] == "por"
    # rota antiga (sem /api) continua respondendo
    assert cliente.get("/health").status_code == 200


def test_pdf_digital(cliente):
    r = enviar(cliente, pdf_digital())
    assert r.status_code == 200, r.get_json()
    dados = r.get_json()
    assert dados["total_paginas"] == 1
    assert dados["paginas_digitais"] == 1
    assert dados["paginas_ocr"] == 0
    assert "=== PAGINA 1 (Digital) ===" in dados["texto"]
    assert "prestação de serviços" in dados["texto"]
    assert dados["chars_totais"] == len(dados["texto"])


def test_lote_de_paginas(cliente):
    r = enviar(cliente, pdf_digital(5), pagina_inicio=2, pagina_fim=3)
    dados = r.get_json()
    assert r.status_code == 200
    assert dados["total_paginas"] == 5  # total do documento, não do lote
    assert [p["pagina"] for p in dados["paginas"]] == [2, 3]
    assert "Pagina numero 1" not in dados["texto"]
    assert "Pagina numero 3" in dados["texto"]


def test_contagem_de_paginas(cliente):
    r = enviar(cliente, pdf_digital(4), rota="/api/ocr/paginas")
    assert r.status_code == 200
    assert r.get_json()["total_paginas"] == 4


@precisa_tesseract
def test_pdf_escaneado(cliente):
    r = enviar(cliente, pdf_escaneado())
    assert r.status_code == 200, r.get_json()
    dados = r.get_json()
    assert dados["paginas_ocr"] == 1
    assert dados["paginas"][0]["tipo"] == "ocr"
    texto = dados["texto"].upper()
    assert "PROCURACAO" in texto
    assert "CIANORTE" in texto


@precisa_tesseract
def test_forcar_ocr(cliente):
    r = enviar(cliente, pdf_digital(), forcar_ocr="true")
    dados = r.get_json()
    assert r.status_code == 200
    assert dados["forcar_ocr"] is True
    assert dados["paginas"][0]["tipo"] == "ocr_forcado"
    assert "Contrato" in dados["texto"]


@precisa_tesseract
def test_health_idioma(cliente):
    dados = cliente.get("/api/ocr/health").get_json()
    assert dados["tesseract_ok"] is True
    assert dados["idioma_ok"] is True
    assert "por" in dados["idiomas"]


def test_rejeita_arquivo_que_nao_e_pdf(cliente):
    r = enviar(cliente, b"conteudo qualquer", nome="planilha.xlsx")
    assert r.status_code == 400
    r = cliente.post("/api/ocr/processar", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


@pytest.mark.parametrize(
    "rota", ["/api/ocr/extrato", "/api/ocr/extrato/recalcular", "/api/ocr/extrato-cartao",
             "/extrato", "/extrato-cartao"]
)
def test_modos_extrato_e_cartao_foram_removidos(cliente, rota):
    r = enviar(cliente, pdf_digital(), rota=rota)
    assert r.status_code in (404, 405)


def test_rotas_api_inexistentes_nao_devolvem_o_site(cliente):
    r = cliente.get("/api/ocr/nao-existe")
    assert r.status_code == 404
    assert r.is_json


def test_site_spa(cliente, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>Visao OCR Pro</html>", encoding="utf-8")
    (tmp_path / "favicon.png").write_bytes(b"png")
    monkeypatch.setattr(ocr_server, "DIST_DIR", str(tmp_path))
    assert b"Visao OCR Pro" in cliente.get("/").data
    assert cliente.get("/favicon.png").data == b"png"
    # rota desconhecida do site cai no index.html (SPA)
    assert b"Visao OCR Pro" in cliente.get("/qualquer/rota").data


def test_processar_pasta(tmp_path):
    (tmp_path / "a.pdf").write_bytes(pdf_digital(2))
    (tmp_path / "B.PDF").write_bytes(pdf_digital(1))
    (tmp_path / "anotacoes.txt").write_text("ignorar", encoding="utf-8")

    pdfs = processar_pasta.listar_pdfs(str(tmp_path))
    assert [os.path.basename(p) for p in pdfs] == ["a.pdf", "B.PDF"]

    vistos = []
    resumo = processar_pasta.processar_lista(
        pdfs, progresso=lambda i, total, nome: vistos.append((i, total, nome))
    )
    assert resumo["ok"] == 2 and resumo["erros"] == 0
    assert vistos == [(1, 2, "a.pdf"), (2, 2, "B.PDF")]
    saida = (tmp_path / "a_texto.txt").read_text(encoding="utf-8")
    assert "=== PAGINA 2 (Digital) ===" in saida
    assert (tmp_path / "relatorio_lote.txt").exists()

    # Já processados: são pulados, a menos que se peça para refazer
    assert processar_pasta.listar_pdfs(str(tmp_path)) == []
    assert len(processar_pasta.listar_pdfs(str(tmp_path), refazer=True)) == 2


def test_processar_pasta_cli(tmp_path, capsys):
    (tmp_path / "c.pdf").write_bytes(pdf_digital(1))
    assert processar_pasta.main([str(tmp_path)]) == 0
    assert (tmp_path / "c_texto.txt").exists()
    assert processar_pasta.main([str(tmp_path / "nao-existe")]) == 1
