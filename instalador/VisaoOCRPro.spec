# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: congela o app_desktop.py (servidor OCR + bandeja) em
# build/pacote/VisaoOCRPro/VisaoOCRPro.exe. Rodado por instalador/build.ps1.
#
# O site (dist/) e o Tesseract portátil (Tesseract-OCR/) NÃO entram no bundle:
# o build.ps1 os copia para o lado do .exe, onde o ocr_server.py os procura.

import os
import sys

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, RAIZ)
from versao import VERSAO_APP  # noqa: E402

ICONE = os.path.join(SPECPATH, "visao-ocr-pro.ico")


def gerar_info_versao():
    """Propriedades do .exe (Detalhes > Versão). Só existe no Windows."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numeros = tuple(int(n) for n in VERSAO_APP.split(".")) + (0,)
    info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numeros, prodvers=numeros),
        kids=[
            StringFileInfo([
                StringTable("041604B0", [
                    StringStruct("CompanyName", "Marques & Gameiro Advocacia"),
                    StringStruct("FileDescription", "Visão OCR Pro"),
                    StringStruct("FileVersion", VERSAO_APP),
                    StringStruct("InternalName", "VisaoOCRPro"),
                    StringStruct("OriginalFilename", "VisaoOCRPro.exe"),
                    StringStruct("ProductName", "Visão OCR Pro"),
                    StringStruct("ProductVersion", VERSAO_APP),
                ])
            ]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )
    arquivo = os.path.join(workpath, "versao_windows.txt")
    os.makedirs(workpath, exist_ok=True)
    with open(arquivo, "w", encoding="utf-8") as f:
        f.write(str(info))
    return arquivo


arquivo_versao = gerar_info_versao() if sys.platform == "win32" else None

a = Analysis(
    [os.path.join(RAIZ, "app_desktop.py")],
    pathex=[RAIZ],
    binaries=[],
    datas=[(ICONE, ".")],
    hiddenimports=[
        "ocr_server",
        "processar_pasta",
        "versao",
        "waitress",
        "pystray._win32",
    ],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "notebook", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VisaoOCRPro",
    console=False,  # sem janela preta; mensagens vão para o log
    icon=ICONE,
    version=arquivo_versao,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="VisaoOCRPro",
    upx=False,
)
