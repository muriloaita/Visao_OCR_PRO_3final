/**
 * Visão OCR Pro — Motor Tesseract
 * Frontend React que consome a API local de OCR (Tesseract + PyMuPDF).
 * Sem dependência de APIs externas ou chaves de API.
 *
 * Versão 3: somente OCR (os modos de extrato bancário e de cartão foram retirados).
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Check,
  Copy,
  Cpu,
  Download,
  Eye,
  FileArchive,
  FileSearch,
  FileText,
  LoaderCircle,
  RefreshCw,
  Square,
  Upload,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { jsPDF } from 'jspdf';
import JSZip from 'jszip';
import { cn } from './lib/utils';
import logoIcone from './assets/logo-icone.png';

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface PaginaInfo {
  pagina: number;
  tipo: 'digital' | 'ocr' | 'ocr_forcado' | 'mista' | 'ocr_erro';
  chars: number;
  imagens_ocr?: number;
}

interface OcrResultado {
  texto: string;
  total_paginas: number;
  paginas_digitais: number;
  paginas_ocr: number;
  paginas_mistas?: number;
  forcar_ocr?: boolean;
  paginas: PaginaInfo[];
  chars_totais: number;
}

interface OcrHealth {
  status: 'online' | 'offline';
  versao_app?: string;
  tesseract_ok: boolean;
  tesseract_versao?: string;
  idioma_padrao?: string;
  idioma_ok?: boolean;
  dpi?: number;
  erro?: string;
}

interface Progresso {
  atual: number;
  total: number;
}

// ─── Parâmetros ───────────────────────────────────────────────────────────────
/** Acima deste número de páginas o PDF é processado em lotes. */
const LIMITE_PAGINAS_LOTE = 40;
/** Páginas por lote (cada lote é uma requisição ao servidor). */
const PAGINAS_POR_LOTE = 25;
/** Máximo de caracteres exibidos na tela (Copiar/Download levam o texto completo). */
const MAX_CHARS_TELA = 150_000;

const MSG_SEM_CONEXAO =
  'Não foi possível conectar ao servidor OCR. Abra o Visão OCR Pro pelo atalho (ou rode python ocr_server.py).';

// ─── Utilitários ──────────────────────────────────────────────────────────────
async function lerJson(resp: Response) {
  if (!(resp.headers.get('content-type') || '').includes('application/json')) {
    throw new Error('Servidor OCR não respondeu corretamente. Verifique se o Visão OCR Pro está aberto.');
  }
  return resp.json();
}

async function copiarTexto(texto: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texto);
      return true;
    }
  } catch {
    // segue para o método alternativo
  }
  try {
    const area = document.createElement('textarea');
    area.value = texto;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

function baixarBlob(blob: Blob, nome: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = nome;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function nomeBase(arquivo: File) {
  return arquivo.name.replace(/\.pdf$/i, '');
}

function montarMarkdown(arquivo: File, r: OcrResultado) {
  return `# OCR: ${arquivo.name}

**Motor:** Tesseract OCR
**Total de páginas:** ${r.total_paginas}
**Páginas digitais:** ${r.paginas_digitais}
**Páginas escaneadas (OCR):** ${r.paginas_ocr}
**Páginas mistas (OCR+Digital):** ${r.paginas_mistas ?? 0}
**Caracteres extraídos:** ${r.chars_totais.toLocaleString('pt-BR')}

---

${r.texto}`;
}

/** Conta as páginas no navegador (pdf-lib) para decidir se processa em lotes. */
async function contarPaginas(arquivo: File): Promise<number> {
  try {
    const { PDFDocument } = await import('pdf-lib');
    const doc = await PDFDocument.load(await arquivo.arrayBuffer(), { ignoreEncryption: true });
    return doc.getPageCount();
  } catch {
    return 0; // PDF que o pdf-lib não abre: o servidor processa de uma vez
  }
}

// ─── Componentes auxiliares ───────────────────────────────────────────────────
const TextoResultado = React.memo(function TextoResultado({ texto }: { texto: string }) {
  const cortado = texto.length > MAX_CHARS_TELA;
  const visivel = cortado ? texto.slice(0, MAX_CHARS_TELA) : texto;
  return (
    <>
      {cortado && (
        <div className="mb-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/25 text-amber-300 text-[11px] leading-relaxed">
          ⚠ Texto muito extenso ({(texto.length / 1000).toFixed(0)} mil caracteres) — exibindo os primeiros{' '}
          {(MAX_CHARS_TELA / 1000).toFixed(0)} mil para não travar o navegador. Use <strong>Copiar</strong> ou os
          botões de download: eles incluem o conteúdo completo.
        </div>
      )}
      <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-white/80 m-0">
        {visivel}
        {cortado && '\n\n[… texto completo disponível via Copiar / Download …]'}
      </pre>
    </>
  );
});

function InfoLinha({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex justify-between items-end border-b border-white/5 pb-2">
      <span className="text-[10px] uppercase text-white/30">{label}</span>
      <span className={cn('text-[11px] font-mono font-bold tracking-tight', highlight ? 'text-emerald-400' : 'text-white/70')}>
        {value}
      </span>
    </div>
  );
}

function BotaoAcao({ onClick, title, children }: { onClick: () => void; title: string; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="px-2.5 py-1.5 hover:bg-white/10 rounded-lg transition-colors flex items-center gap-1.5 text-white/50 hover:text-white shrink-0"
    >
      {children}
    </button>
  );
}

// ─── Componente principal ─────────────────────────────────────────────────────
export default function App() {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [processando, setProcessando] = useState(false);
  const [progresso, setProgresso] = useState<Progresso | null>(null);
  const [resultado, setResultado] = useState<OcrResultado | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);
  const [saude, setSaude] = useState<OcrHealth | null>(null);
  const [verificando, setVerificando] = useState(false);
  const [forcarOcr, setForcarOcr] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const execucaoRef = useRef(0); // invalida respostas de execuções canceladas

  const verificarSaude = useCallback(async (): Promise<OcrHealth> => {
    setVerificando(true);
    let dados: OcrHealth;
    try {
      const resp = await fetch('/api/ocr/health', { signal: AbortSignal.timeout(6000) });
      dados = await lerJson(resp);
    } catch {
      dados = { status: 'offline', tesseract_ok: false, erro: 'Servidor OCR não está rodando.' };
    }
    setSaude(dados);
    setVerificando(false);
    return dados;
  }, []);

  // Ao abrir, tenta algumas vezes: o servidor pode estar terminando de subir
  useEffect(() => {
    let cancelado = false;
    let espera: ReturnType<typeof setTimeout>;
    const tentar = async (restantes: number) => {
      const dados = await verificarSaude();
      if (!cancelado && dados.status !== 'online' && restantes > 0) {
        espera = setTimeout(() => tentar(restantes - 1), 2000);
      }
    };
    tentar(5);
    return () => {
      cancelado = true;
      clearTimeout(espera);
    };
  }, [verificarSaude]);

  const escolherArquivo = (novo?: File) => {
    if (novo && (novo.type === 'application/pdf' || novo.name.toLowerCase().endsWith('.pdf'))) {
      setArquivo(novo);
      setErro(null);
      setResultado(null);
    } else {
      setErro('Por favor, selecione um arquivo PDF válido.');
    }
  };

  const cancelar = () => {
    abortRef.current?.abort();
    execucaoRef.current++;
    setProcessando(false);
    setProgresso(null);
  };

  const processar = async () => {
    if (!arquivo) return;
    abortRef.current?.abort();
    const controle = new AbortController();
    abortRef.current = controle;
    const execucao = ++execucaoRef.current;
    const ativa = () => execucao === execucaoRef.current;

    setProcessando(true);
    setErro(null);
    setResultado(null);
    setProgresso(null);

    const enviarLote = async (inicio?: number, fim?: number): Promise<OcrResultado> => {
      const form = new FormData();
      form.append('file', arquivo);
      form.append('forcar_ocr', forcarOcr ? 'true' : 'false');
      if (inicio) form.append('pagina_inicio', String(inicio));
      if (fim) form.append('pagina_fim', String(fim));
      const resp = await fetch('/api/ocr/processar', { method: 'POST', body: form, signal: controle.signal });
      const dados = await lerJson(resp);
      if (!resp.ok) throw new Error(dados.erro || dados.detalhe || 'Erro desconhecido no processamento.');
      return dados;
    };

    try {
      const totalPaginas = await contarPaginas(arquivo);

      // Documento pequeno: uma requisição só
      if (!totalPaginas || totalPaginas <= LIMITE_PAGINAS_LOTE) {
        const unico = await enviarLote();
        if (ativa()) setResultado(unico);
        return;
      }

      // Documento extenso: lotes de páginas, com progresso
      setProgresso({ atual: 0, total: totalPaginas });
      const lotes: OcrResultado[] = [];
      let falha: string | null = null;
      for (let inicio = 1; inicio <= totalPaginas; inicio += PAGINAS_POR_LOTE) {
        const fim = Math.min(inicio + PAGINAS_POR_LOTE - 1, totalPaginas);
        try {
          const lote = await enviarLote(inicio, fim);
          if (!ativa()) return;
          lotes.push(lote);
          setProgresso({ atual: fim, total: totalPaginas });
        } catch (e) {
          if ((e as Error)?.name === 'AbortError' || !ativa()) return;
          falha = `Falha no lote das páginas ${inicio}–${fim}: ${(e as Error).message}. Exibindo o texto extraído até aqui.`;
          break;
        }
      }
      if (!ativa()) return;
      if (!lotes.length) throw new Error(falha || 'Nenhuma página pôde ser processada.');

      const texto = lotes.map((l) => l.texto).filter(Boolean).join('\n\n');
      const soma = (campo: 'paginas_digitais' | 'paginas_ocr' | 'paginas_mistas') =>
        lotes.reduce((total, l) => total + (l[campo] || 0), 0);
      setResultado({
        texto,
        total_paginas: totalPaginas,
        paginas_digitais: soma('paginas_digitais'),
        paginas_ocr: soma('paginas_ocr'),
        paginas_mistas: soma('paginas_mistas'),
        paginas: lotes.flatMap((l) => l.paginas || []),
        chars_totais: texto.length,
        forcar_ocr: forcarOcr,
      });
      if (falha) setErro(falha);
    } catch (e) {
      const err = e as Error;
      if (err?.name === 'AbortError' || !ativa()) return;
      console.error(err);
      setErro(err.name === 'TypeError' ? MSG_SEM_CONEXAO : err.message || 'Erro crítico no processamento. Verifique o arquivo.');
    } finally {
      if (ativa()) {
        setProcessando(false);
        setProgresso(null);
      }
    }
  };

  // ─── Exportações ────────────────────────────────────────────────────────────
  const copiarResultado = async () => {
    if (!resultado?.texto) return;
    if (await copiarTexto(resultado.texto)) {
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } else {
      setErro('Não foi possível copiar. Selecione o texto manualmente.');
    }
  };

  const baixarTxt = () => {
    if (!resultado?.texto || !arquivo) return;
    baixarBlob(new Blob([resultado.texto], { type: 'text/plain;charset=utf-8' }), `OCR_${nomeBase(arquivo)}.txt`);
  };

  const baixarMarkdown = () => {
    if (!resultado?.texto || !arquivo) return;
    baixarBlob(
      new Blob([montarMarkdown(arquivo, resultado)], { type: 'text/markdown;charset=utf-8' }),
      `OCR_${nomeBase(arquivo)}_${Date.now()}.md`,
    );
  };

  const baixarPdf = () => {
    if (!resultado?.texto || !arquivo) return;
    const doc = new jsPDF();
    const margem = 10;
    const altura = 5;
    const larguraPagina = doc.internal.pageSize.getWidth();
    const alturaPagina = doc.internal.pageSize.getHeight();
    doc.setFontSize(10);
    const linhas: string[] = doc.splitTextToSize(resultado.texto, larguraPagina - margem * 2);
    let y = 20;
    for (const linha of linhas) {
      if (y > alturaPagina - margem) {
        doc.addPage();
        y = margem + 5;
      }
      doc.text(linha, margem, y);
      y += altura;
    }
    doc.save(`OCR_${nomeBase(arquivo)}.pdf`);
  };

  const baixarZip = async () => {
    if (!resultado || !arquivo) return;
    const zip = new JSZip();
    zip.file(`ORIGINAL_${arquivo.name}`, arquivo);
    zip.file(`OCR_${nomeBase(arquivo)}.txt`, resultado.texto);
    zip.file(`OCR_${nomeBase(arquivo)}.md`, montarMarkdown(arquivo, resultado));
    baixarBlob(await zip.generateAsync({ type: 'blob' }), `PACOTE_OCR_${nomeBase(arquivo)}.zip`);
  };

  // ─── Derivados ──────────────────────────────────────────────────────────────
  const online = saude?.status === 'online' && saude?.tesseract_ok;
  const semPortugues = online && saude?.idioma_ok === false;
  const total = resultado?.total_paginas || 0;
  const pctDigital = total ? Math.round((resultado!.paginas_digitais / total) * 100) : 0;
  const pctOcr = total ? Math.round((resultado!.paginas_ocr / total) * 100) : 0;
  const paginasComErro = resultado?.paginas.filter((p) => p.tipo === 'ocr_erro').length || 0;
  const palavras = useMemo(() => {
    const t = resultado?.texto?.trim();
    return t ? t.split(/\s+/).length : 0;
  }, [resultado?.texto]);

  return (
    <div className="min-h-screen bg-[#0F0F0F] text-white font-sans">
      {/* ─── Cabeçalho ─── */}
      <header className="border-b border-white/10 bg-[#0F0F0F]/90 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={logoIcone} alt="Visão OCR Pro" className="w-10 h-10 object-contain drop-shadow-lg" />
            <div>
              <h1 className="font-bold text-lg tracking-tight">Visão OCR Pro</h1>
              <p className="text-[10px] uppercase tracking-widest text-white/40 font-semibold font-mono">
                Motor: Tesseract Open Source
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={verificarSaude}
              disabled={verificando}
              className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-xs font-mono"
              title="Verificar servidor OCR"
            >
              {verificando ? (
                <LoaderCircle className="w-3 h-3 animate-spin text-amber-400" />
              ) : (
                <RefreshCw className="w-3 h-3 text-white/40" />
              )}
              <span className="text-white/50 uppercase text-[9px] tracking-wider">Verificar</span>
            </button>
            <div
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-full border text-[10px] font-mono font-bold uppercase tracking-wide transition-all',
                online
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : 'bg-red-500/10 border-red-500/30 text-red-400',
              )}
            >
              {online ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
              <span>{online ? 'OCR Online' : 'OCR Offline'}</span>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-10">
        {/* ─── Avisos do servidor ─── */}
        <AnimatePresence>
          {saude && !online && (
            <motion.div
              key="aviso-offline"
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mb-6 p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 flex items-start gap-3"
            >
              <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-amber-300 font-bold text-sm uppercase tracking-wide mb-1">Servidor OCR não detectado</p>
                <p className="text-amber-200/70 text-xs leading-relaxed">
                  {saude.status === 'online'
                    ? 'O servidor está no ar, mas o Tesseract não foi encontrado. Reinstale o Visão OCR Pro.'
                    : 'Abra o Visão OCR Pro pelo atalho da Área de Trabalho ou do Menu Iniciar. Rodando pelo código-fonte:'}
                </p>
                {saude.status !== 'online' && (
                  <code className="block mt-2 px-3 py-2 bg-black/40 rounded-lg text-amber-300 text-xs font-mono border border-amber-500/20">
                    pip install -r requirements.txt &amp;&amp; python ocr_server.py
                  </code>
                )}
              </div>
            </motion.div>
          )}
          {semPortugues && (
            <motion.div
              key="aviso-idioma"
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mb-6 p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 flex items-start gap-3"
            >
              <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <p className="text-amber-200/80 text-xs leading-relaxed">
                O Tesseract está instalado, mas <strong>sem o idioma português</strong> (por.traineddata). O OCR de
                páginas escaneadas vai falhar até o idioma ser instalado.
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="grid lg:grid-cols-12 gap-8">
          {/* ─── Coluna esquerda: upload e parâmetros ─── */}
          <div className="lg:col-span-4 space-y-5">
            <section className="border rounded-2xl p-6 backdrop-blur-sm bg-white/5 border-white/10">
              <h2 className="text-[10px] font-bold uppercase tracking-widest mb-5 flex items-center gap-2 text-white/50">
                <Upload className="w-3 h-3" />
                Upload de Documento
              </h2>

              <div
                onDrop={(e) => {
                  e.preventDefault();
                  escolherArquivo(e.dataTransfer.files[0]);
                }}
                onDragOver={(e) => e.preventDefault()}
                onClick={() => inputRef.current?.click()}
                className={cn(
                  'relative border-2 border-dashed rounded-xl transition-all duration-300 cursor-pointer group',
                  arquivo
                    ? 'border-emerald-500/50 bg-emerald-500/10'
                    : 'border-white/10 hover:border-amber-500/40 hover:bg-amber-500/5',
                )}
              >
                <input
                  ref={inputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={(e) => {
                    escolherArquivo(e.target.files?.[0]);
                    e.target.value = '';
                  }}
                  className="hidden"
                />
                <div className="p-8 text-center">
                  <div className="mb-4 flex justify-center">
                    {arquivo ? (
                      <div className="text-white p-3 rounded-full bg-emerald-500">
                        <Check className="w-6 h-6" />
                      </div>
                    ) : (
                      <div className="bg-white/5 p-4 rounded-full group-hover:scale-110 transition-transform">
                        <FileText className="w-8 h-8 text-white/30" />
                      </div>
                    )}
                  </div>
                  <p className="text-sm font-semibold mb-1 break-all">{arquivo ? arquivo.name : 'Arraste seu PDF aqui'}</p>
                  <p className="text-[11px] text-white/40 uppercase tracking-wider">
                    {arquivo ? `${(arquivo.size / 1024 / 1024).toFixed(2)} MB` : 'ou clique para navegar'}
                  </p>
                </div>
              </div>

              {/* Forçar OCR */}
              <div className="mt-5 pt-4 border-t border-white/10">
                <label htmlFor="toggle-forcar-ocr" className="flex items-start gap-3 cursor-pointer group">
                  <div className="relative shrink-0 mt-0.5">
                    <input
                      id="toggle-forcar-ocr"
                      type="checkbox"
                      className="sr-only"
                      checked={forcarOcr}
                      onChange={(e) => setForcarOcr(e.target.checked)}
                    />
                    <div
                      className={cn(
                        'w-10 h-5 rounded-full transition-all duration-300 border',
                        forcarOcr ? 'bg-amber-500 border-amber-400' : 'bg-white/10 border-white/20 group-hover:bg-white/15',
                      )}
                    >
                      <div
                        className={cn(
                          'absolute top-0.5 w-4 h-4 rounded-full shadow transition-all duration-300',
                          forcarOcr ? 'left-[22px] bg-white' : 'left-0.5 bg-white/50 group-hover:bg-white/70',
                        )}
                      />
                    </div>
                  </div>
                  <div>
                    <p
                      className={cn(
                        'text-xs font-bold leading-tight',
                        forcarOcr ? 'text-amber-300' : 'text-white/60 group-hover:text-white/80',
                      )}
                    >
                      Forçar OCR em Todas as Páginas
                    </p>
                    <p className="text-[10px] text-white/30 mt-0.5 leading-relaxed">
                      {forcarOcr
                        ? '⚡ Tesseract ativo em todas as páginas — ideal para PDFs escaneados'
                        : 'Detecção automática: digital ou escaneada (padrão)'}
                    </p>
                  </div>
                </label>
              </div>

              {/* Processar / Cancelar */}
              <button
                id="btn-processar"
                onClick={processar}
                disabled={!arquivo || processando || !online}
                className={cn(
                  'w-full mt-5 py-4 rounded-xl font-bold uppercase tracking-widest flex items-center justify-center gap-3 transition-all text-sm',
                  arquivo && !processando && online
                    ? 'bg-gradient-to-r from-amber-400 to-orange-500 text-black hover:from-amber-300 hover:to-orange-400 shadow-lg shadow-orange-500/20 active:scale-[0.98]'
                    : 'bg-white/5 text-white/20 cursor-not-allowed',
                )}
              >
                {processando ? (
                  <>
                    <LoaderCircle className="w-5 h-5 animate-spin" />
                    <span>{progresso ? `Processando OCR... ${progresso.atual}/${progresso.total} págs` : 'Processando OCR...'}</span>
                  </>
                ) : (
                  <>
                    <FileSearch className="w-5 h-5" />
                    <span>Iniciar OCR</span>
                  </>
                )}
              </button>

              {processando && (
                <button
                  onClick={cancelar}
                  className="w-full mt-2 py-2 rounded-xl text-[10px] font-bold uppercase tracking-widest flex items-center justify-center gap-2 text-white/40 hover:text-white/80 hover:bg-white/5 border border-white/10 transition-all"
                >
                  <Square className="w-3 h-3" />
                  Cancelar
                </button>
              )}

              {processando && progresso && progresso.total > 0 && (
                <div className="mt-3">
                  <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-amber-400 to-orange-500 transition-all duration-300"
                      style={{ width: `${Math.round((progresso.atual / progresso.total) * 100)}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-white/40 mt-1.5 font-mono text-center">
                    Documento extenso — processando em lotes ({progresso.atual}/{progresso.total} páginas)
                  </p>
                </div>
              )}

              {erro && (
                <motion.div
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mt-4 p-4 bg-red-500/10 border border-red-500/30 rounded-xl flex items-start gap-3"
                >
                  <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                  <p className="text-[11px] font-semibold text-red-300 leading-relaxed">{erro}</p>
                </motion.div>
              )}
            </section>

            {/* Motor de OCR */}
            <section className="bg-white/5 border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
              <h3 className="text-[10px] font-bold uppercase tracking-widest mb-4 flex items-center gap-2 text-white/50">
                <Cpu className="w-3 h-3" />
                Motor de OCR
              </h3>
              <div className="space-y-3">
                <InfoLinha label="Engine" value="Tesseract OSS" />
                <InfoLinha label="Backend" value="Python + Flask" />
                <InfoLinha label="Extração Digital" value="PyMuPDF (fitz)" />
                <InfoLinha label="Idioma Padrão" value={saude?.idioma_padrao?.toUpperCase() || 'POR'} />
                <InfoLinha label="Resolução" value={saude?.dpi ? `${saude.dpi} DPI` : '300 DPI'} />
                <InfoLinha label="Tesseract" value={saude?.tesseract_versao || '—'} />
                <InfoLinha label="Versão do App" value={saude?.versao_app || '—'} />
                <InfoLinha label="API Key" value="Não necessária" highlight />
              </div>
            </section>

            {/* Estatísticas */}
            <AnimatePresence>
              {resultado && (
                <motion.section
                  key="estatisticas"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="border rounded-2xl p-6 backdrop-blur-sm bg-gradient-to-br from-amber-500/10 to-orange-500/10 border-amber-500/20"
                >
                  <h3 className="text-[10px] font-bold uppercase tracking-widest mb-4 text-amber-400">Resultado da Extração</h3>
                  <div className="space-y-3">
                    <InfoLinha label="Total de Páginas" value={String(resultado.total_paginas)} />
                    {resultado.forcar_ocr ? (
                      <InfoLinha label="Modo OCR" value="⚡ Forçado (100% Tesseract)" highlight />
                    ) : (
                      <>
                        <InfoLinha label="Páginas Digitais" value={`${resultado.paginas_digitais} (${pctDigital}%)`} />
                        <InfoLinha label="Páginas OCR" value={`${resultado.paginas_ocr} (${pctOcr}%)`} />
                        {(resultado.paginas_mistas ?? 0) > 0 && (
                          <InfoLinha label="Páginas Mistas" value={`${resultado.paginas_mistas} — OCR+Digital`} highlight />
                        )}
                      </>
                    )}
                    {paginasComErro > 0 && <InfoLinha label="Páginas com Erro" value={String(paginasComErro)} />}
                    <InfoLinha label="Palavras" value={palavras.toLocaleString('pt-BR')} />
                    <InfoLinha label="Caracteres" value={resultado.chars_totais.toLocaleString('pt-BR')} />
                  </div>
                  <div className="mt-4">
                    <div className="flex text-[9px] font-mono justify-between mb-1 text-white/40 uppercase">
                      <span>{resultado.forcar_ocr ? 'OCR Forçado' : 'Digital'}</span>
                      <span>{resultado.forcar_ocr ? '100% Tesseract' : 'OCR (Scan)'}</span>
                    </div>
                    <div className="h-2 rounded-full bg-white/10 overflow-hidden flex">
                      {resultado.forcar_ocr ? (
                        <div className="h-full w-full bg-amber-500" />
                      ) : (
                        <>
                          <div className="h-full transition-all duration-700 bg-emerald-500" style={{ width: `${pctDigital}%` }} />
                          <div className="h-full transition-all duration-700 bg-amber-500" style={{ width: `${pctOcr}%` }} />
                        </>
                      )}
                    </div>
                  </div>
                </motion.section>
              )}
            </AnimatePresence>
          </div>

          {/* ─── Coluna direita: resultado ─── */}
          <div className="lg:col-span-8 flex flex-col min-h-[600px]">
            <div className="border rounded-2xl shadow-sm flex flex-col flex-1 overflow-hidden backdrop-blur-sm bg-white/5 border-white/10">
              <div className="px-6 pt-4 pb-0 border-b border-white/10 bg-white/5 sticky top-0 z-10 backdrop-blur-sm">
                <div className="flex items-center gap-2 pb-3">
                  <div className="w-2 h-2 rounded-full bg-amber-400" />
                  <h2 className="text-[10px] font-bold uppercase tracking-widest text-white/70">Painel de Resultados</h2>
                </div>
                <AnimatePresence>
                  {resultado && (
                    <motion.div
                      key="acoes"
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -6 }}
                      className="flex items-center gap-1 pb-3 overflow-x-auto"
                    >
                      <BotaoAcao onClick={copiarResultado} title="Copiar texto OCR">
                        {copiado ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span className="text-[10px] font-bold uppercase tracking-wider">{copiado ? 'Copiado' : 'Copiar OCR'}</span>
                      </BotaoAcao>
                      <div className="w-[1px] h-4 bg-white/10 mx-1 shrink-0" />
                      <BotaoAcao onClick={baixarTxt} title="Exportar texto (.txt)">
                        <Download className="w-3.5 h-3.5" />
                        <span className="text-[10px] font-bold uppercase tracking-wider">TXT</span>
                      </BotaoAcao>
                      <BotaoAcao onClick={baixarMarkdown} title="Exportar Markdown (.md)">
                        <Download className="w-3.5 h-3.5" />
                        <span className="text-[10px] font-bold uppercase tracking-wider">Markdown</span>
                      </BotaoAcao>
                      <BotaoAcao onClick={baixarPdf} title="Exportar PDF com o texto extraído">
                        <Download className="w-3.5 h-3.5" />
                        <span className="text-[10px] font-bold uppercase tracking-wider">PDF</span>
                      </BotaoAcao>
                      <div className="w-[1px] h-4 bg-white/10 mx-1 shrink-0" />
                      <button
                        id="btn-baixar-zip"
                        onClick={baixarZip}
                        title="Original + TXT + Markdown"
                        className="px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 shadow-sm active:scale-95 shrink-0 bg-gradient-to-r from-amber-400 to-orange-500 text-black hover:from-amber-300 hover:to-orange-400"
                      >
                        <FileArchive className="w-3.5 h-3.5" />
                        <span className="text-[10px] font-bold uppercase tracking-wider">ZIP Completo</span>
                      </button>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              <div
                className={cn(
                  'flex-1 p-8 overflow-y-auto text-[13px] leading-relaxed relative',
                  !resultado && 'flex items-center justify-center',
                )}
              >
                {resultado ? (
                  <motion.div key="texto-ocr" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-none">
                    <TextoResultado texto={resultado.texto} />
                  </motion.div>
                ) : (
                  <div className="text-center max-w-sm space-y-5 opacity-30 select-none">
                    <div className="flex justify-center">
                      <div
                        className={cn(
                          'p-10 border-4 border-dashed border-white/10 rounded-full',
                          processando && 'animate-pulse border-amber-500/50 bg-amber-500/5',
                        )}
                      >
                        {processando ? (
                          <LoaderCircle className="w-14 h-14 animate-spin text-amber-400" />
                        ) : (
                          <FileText className="w-14 h-14 text-white/30" />
                        )}
                      </div>
                    </div>
                    <div className="uppercase tracking-[0.2em] font-bold text-sm">
                      {processando ? 'Processando com Tesseract...' : 'Aguardando Input...'}
                    </div>
                    <p className="text-[11px] font-medium leading-normal italic px-4 text-white/50">
                      {processando
                        ? 'Detectando páginas digitais e aplicando OCR nas escaneadas.'
                        : '"Visão computacional local, sem nuvem, sem API keys."'}
                    </p>
                  </div>
                )}
              </div>

              {resultado && (
                <div className="px-6 py-2.5 bg-white/5 border-t border-white/10 flex justify-between items-center shrink-0">
                  <span className="text-[9px] font-mono text-white/30 uppercase tracking-widest">
                    ✓ Extração concluída · Tesseract OCR
                  </span>
                  <div className="flex items-center gap-4">
                    <span className="text-[9px] font-mono text-white/30 uppercase">{resultado.total_paginas} pág.</span>
                    <span className="text-[9px] font-mono text-white/30 uppercase">{palavras.toLocaleString('pt-BR')} palavras</span>
                    <span className="text-[9px] font-mono text-white/30 uppercase">
                      {resultado.chars_totais.toLocaleString('pt-BR')} chars
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      <footer className="mt-12 py-8 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4 opacity-30 hover:opacity-70 transition-opacity">
          <div className="flex items-center gap-4 flex-wrap justify-center">
            <Eye className="w-4 h-4" />
            <span className="text-[10px] font-bold uppercase tracking-[0.2em]">Visão OCR Pro</span>
            <div className="w-[1px] h-3 bg-white/30" />
            <span className="text-[10px] font-bold uppercase tracking-[0.2em]">Powered by Murilo Aita Marques</span>
            <div className="w-[1px] h-3 bg-white/30" />
            <span className="text-[10px] font-bold uppercase tracking-[0.2em]">100% Local · Sem API Keys</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
