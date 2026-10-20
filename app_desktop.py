"""
app_desktop.py
==============
Inicializador do Visão OCR Pro instalado (vira o VisaoOCRPro.exe).

- Sobe o servidor OCR (waitress) em http://localhost:5002, sem janela de console.
- Abre o aplicativo no navegador padrão.
- Fica um ícone na bandeja do Windows: Abrir / Processar pasta de PDFs / Sair.
- Se o servidor já estiver no ar, apenas abre o navegador (instância única).

Uso:
    VisaoOCRPro.exe                    -> servidor + bandeja + navegador
    VisaoOCRPro.exe --servidor         -> servidor + bandeja, sem abrir o navegador
                                          (usado ao iniciar junto com o Windows)
    VisaoOCRPro.exe --sem-bandeja      -> só o servidor, sem ícone (testes/CI)
    VisaoOCRPro.exe --processar-pasta  -> escolhe uma pasta e gera um .txt por PDF

Em desenvolvimento, o mesmo arquivo roda com: python app_desktop.py
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

HOST = "127.0.0.1"  # apenas esta máquina: os documentos são sigilosos
PORTA = 5002
URL_APP = f"http://localhost:{PORTA}"
URL_SAUDE = f"http://{HOST}:{PORTA}/api/ocr/health"
NOME_APP = "Visão OCR Pro"

CONGELADO = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if CONGELADO else __file__))
# Recursos embutidos pelo PyInstaller (ícone) ficam em sys._MEIPASS
RECURSOS_DIR = getattr(sys, "_MEIPASS", BASE_DIR)


def pasta_logs() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    pasta = os.path.join(base, "VisaoOCRPro", "logs")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def preparar_saida():
    """
    No executável sem console (e no pythonw) sys.stdout/sys.stderr são None.
    Redireciona para um arquivo de log, útil para suporte.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log = open(
            os.path.join(pasta_logs(), "servidor.log"),
            "a",
            encoding="utf-8",
            buffering=1,
        )
    except OSError:
        log = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    print(f"\n===== {NOME_APP} iniciado em {time.strftime('%d/%m/%Y %H:%M:%S')} =====")


# Sem proxy: o servidor é local. Algumas redes de escritório configuram um
# proxy no Windows que não libera o localhost.
_SEM_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ler_saude(timeout: float = 1.5):
    """Retorna o JSON do /api/ocr/health, ou None se nada responder."""
    try:
        with _SEM_PROXY.open(URL_SAUDE, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def porta_ocupada() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((HOST, PORTA)) == 0


def mensagem(texto: str, erro: bool = False):
    """Caixa de mensagem do Windows (ou print fora do Windows)."""
    print(("[ERRO] " if erro else "[INFO] ") + texto)
    if sys.platform == "win32":
        import ctypes

        icone = 0x10 if erro else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, texto, NOME_APP, icone)


def abrir_navegador():
    webbrowser.open(URL_APP)


def iniciar_servidor():
    """Sobe o waitress em segundo plano e devolve o objeto do servidor."""
    from waitress import create_server

    import ocr_server

    servidor = create_server(ocr_server.app, host=HOST, port=PORTA, threads=6)
    threading.Thread(target=servidor.run, name="waitress", daemon=True).start()
    return servidor


def aguardar_servidor(segundos: float = 30) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        if ler_saude():
            return True
        time.sleep(0.3)
    return False


def comando_proprio(*args: str) -> list:
    """Linha de comando para relançar este mesmo programa com outros argumentos."""
    if CONGELADO:
        return [sys.executable, *args]
    return [sys.executable, os.path.abspath(__file__), *args]


def abrir_processamento_pasta():
    # Processo separado: a janela (tkinter) precisa da thread principal,
    # que aqui está ocupada com o ícone da bandeja.
    subprocess.Popen(comando_proprio("--processar-pasta"), cwd=BASE_DIR)


def carregar_icone():
    from PIL import Image

    for nome in ("visao-ocr-pro.ico", os.path.join("instalador", "visao-ocr-pro.ico")):
        caminho = os.path.join(RECURSOS_DIR, nome)
        if os.path.exists(caminho):
            return Image.open(caminho)
    return Image.new("RGB", (64, 64), (200, 30, 40))


def rodar_bandeja(servidor):
    """Ícone na bandeja do Windows. Bloqueia até o usuário escolher 'Sair'."""
    import pystray

    def sair(icone, _item):
        icone.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir Visão OCR Pro", lambda: abrir_navegador(), default=True),
        pystray.MenuItem("Processar pasta de PDFs...", lambda: abrir_processamento_pasta()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair (encerrar o servidor)", sair),
    )
    icone = pystray.Icon(
        "VisaoOCRPro",
        carregar_icone(),
        f"{NOME_APP} — {URL_APP}",
        menu,
    )
    icone.run()
    servidor.close()


def modo_servidor(abrir: bool, bandeja: bool) -> int:
    saude = ler_saude()
    if saude:
        from versao import VERSAO_APP

        if saude.get("versao_app") == VERSAO_APP:
            # Já está rodando (outra janela/atalho): só abre o navegador
            if abrir:
                abrir_navegador()
            return 0
        mensagem(
            "Uma versão antiga do Visão OCR Pro ainda está em execução "
            f"(porta {PORTA}).\n\nReinicie o computador ou encerre o processo "
            "antigo no Gerenciador de Tarefas e abra o programa de novo.",
            erro=True,
        )
        return 1

    if porta_ocupada():
        mensagem(
            f"A porta {PORTA} está sendo usada por outro programa.\n\n"
            "Feche esse programa (ou reinicie o computador) e abra o "
            "Visão OCR Pro novamente.",
            erro=True,
        )
        return 1

    servidor = iniciar_servidor()
    if not aguardar_servidor():
        mensagem(
            "O servidor OCR não respondeu a tempo.\n\n"
            f"Veja o log em: {os.path.join(pasta_logs(), 'servidor.log')}",
            erro=True,
        )
        return 1
    print(f"[OK] Servidor no ar: {URL_APP}")

    if abrir:
        abrir_navegador()

    if bandeja:
        try:
            rodar_bandeja(servidor)
            return 0
        except Exception as e:  # sem bandeja disponível: segue só com o servidor
            print(f"[AVISO] Ícone da bandeja indisponível: {e}")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        servidor.close()
    return 0


def modo_processar_pasta() -> int:
    """Janela simples: escolhe a pasta, mostra o progresso e o resumo final."""
    import queue
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    raiz = tk.Tk()
    raiz.withdraw()
    pasta = filedialog.askdirectory(title="Escolha a pasta com os PDFs para o OCR")
    if not pasta:
        return 0

    import processar_pasta

    pdfs = processar_pasta.listar_pdfs(pasta)
    if not pdfs:
        messagebox.showinfo(
            NOME_APP,
            "Nenhum PDF pendente nesta pasta.\n\n"
            "(PDFs que já têm o arquivo _texto.txt ao lado são ignorados.)",
        )
        return 0

    janela = tk.Toplevel(raiz)
    janela.title(f"{NOME_APP} — Processando pasta")
    janela.geometry("520x150")
    janela.resizable(False, False)
    rotulo = tk.Label(janela, text="Preparando...", anchor="w", justify="left")
    rotulo.pack(fill="x", padx=16, pady=(16, 8))
    barra = ttk.Progressbar(janela, maximum=len(pdfs), length=480)
    barra.pack(padx=16)
    detalhe = tk.Label(janela, text=pasta, anchor="w", fg="#666")
    detalhe.pack(fill="x", padx=16, pady=8)
    janela.protocol("WM_DELETE_WINDOW", lambda: None)  # não fechar no meio

    fila: "queue.Queue" = queue.Queue()

    def trabalhar():
        def progresso(indice, total, nome):
            fila.put(("andamento", indice, total, nome))

        try:
            resumo = processar_pasta.processar_lista(pdfs, progresso=progresso)
            fila.put(("fim", resumo))
        except Exception as e:
            fila.put(("erro", str(e)))

    def acompanhar():
        try:
            while True:
                evento = fila.get_nowait()
                if evento[0] == "andamento":
                    _, indice, total, nome = evento
                    rotulo.config(text=f"Arquivo {indice} de {total}: {nome}")
                    barra["value"] = indice - 1
                elif evento[0] == "fim":
                    resumo = evento[1]
                    barra["value"] = len(pdfs)
                    messagebox.showinfo(
                        NOME_APP,
                        f"Concluído: {resumo['ok']} PDF(s) processado(s), "
                        f"{resumo['erros']} com erro.\n\n"
                        f"Os textos foram salvos ao lado de cada PDF (_texto.txt).\n"
                        f"Relatório: {resumo['relatorio']}",
                    )
                    if sys.platform == "win32":
                        os.startfile(pasta)
                    raiz.destroy()
                    return
                elif evento[0] == "erro":
                    messagebox.showerror(NOME_APP, f"Falha no processamento:\n{evento[1]}")
                    raiz.destroy()
                    return
        except queue.Empty:
            pass
        raiz.after(300, acompanhar)

    threading.Thread(target=trabalhar, daemon=True).start()
    raiz.after(300, acompanhar)
    raiz.mainloop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=NOME_APP)
    parser.add_argument("--servidor", "--sem-navegador", dest="sem_navegador",
                        action="store_true", help="não abre o navegador")
    parser.add_argument("--sem-bandeja", action="store_true",
                        help="não mostra o ícone na bandeja")
    parser.add_argument("--processar-pasta", action="store_true",
                        help="processa todos os PDFs de uma pasta")
    args = parser.parse_args(argv)

    os.chdir(BASE_DIR)
    preparar_saida()
    if args.processar_pasta:
        return modo_processar_pasta()
    return modo_servidor(abrir=not args.sem_navegador, bandeja=not args.sem_bandeja)


if __name__ == "__main__":
    sys.exit(main())
