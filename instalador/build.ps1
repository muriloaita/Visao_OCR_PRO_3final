<#
.SYNOPSIS
  Gera o pacote completo do Visao OCR Pro: instalador (Setup .exe) e ZIP portatil.

.DESCRIPTION
  1. Compila o site (npm ci + npm run build)            -> dist\
  2. Prepara o Tesseract portatil com portugues         -> build\Tesseract-OCR\
  3. Roda os testes automatizados (pytest)
  4. Congela o servidor com o PyInstaller               -> build\pacote\VisaoOCRPro\
  5. Testa o executavel congelado (sobe o servidor e faz OCR de um PDF)
  6. Gera o instalador com o Inno Setup                 -> saida\VisaoOCRPro-Setup-<versao>.exe
  7. Gera o ZIP portatil (roda sem instalar)            -> saida\VisaoOCRPro-<versao>-portatil.zip

  Requisitos na maquina que gera o pacote: Python 3.11+, Node.js 18+ e
  Inno Setup 6 (se faltar e houver Chocolatey, e instalado automaticamente).
  A maquina que USA o programa nao precisa de nada disso.

.PARAMETER TesseractOrigem
  Pasta de um Tesseract ja existente para reaproveitar (ex: "C:\Program Files\Tesseract-OCR"
  ou a pasta extraida do Tesseract-OCR-5.5.0-portatil.zip). Sem ela, o script baixa o
  instalador oficial do UB-Mannheim.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File instalador\build.ps1
#>
param(
  [string]$TesseractOrigem = "",
  [switch]$PularTestes,
  [switch]$SemInstalador
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest fica muito mais rapido
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Raiz      = Split-Path -Parent $PSScriptRoot
$Build     = Join-Path $Raiz 'build'
$Downloads = Join-Path $Build 'downloads'
$TessDir   = Join-Path $Build 'Tesseract-OCR'
$Pacote    = Join-Path $Build 'pacote\VisaoOCRPro'
$Saida     = Join-Path $Raiz 'saida'

# Tesseract (UB-Mannheim). A versao mais recente e buscada pela API do GitHub;
# este link e a reserva caso a API nao responda.
$TessReserva = 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.3.20260724/tesseract-ocr-w64-setup-5.5.3.20260724.exe'
# Modelos de idioma (tessdata padrao, o mesmo que o instalador do UB-Mannheim baixa)
$UrlsIdioma = @{
  'por' = @('https://github.com/tesseract-ocr/tessdata/raw/4.1.0/por.traineddata',
            'https://github.com/tesseract-ocr/tessdata/raw/main/por.traineddata')
  'osd' = @('https://github.com/tesseract-ocr/tessdata/raw/4.1.0/osd.traineddata',
            'https://github.com/tesseract-ocr/tessdata/raw/main/osd.traineddata')
}
$IdiomasMantidos = @('por', 'eng', 'osd')

function Etapa([string]$texto) { Write-Host "`n==== $texto ====" -ForegroundColor Cyan }

function Nativo([scriptblock]$bloco, [string]$descricao) {
  & $bloco
  if ($LASTEXITCODE -ne 0) { throw "$descricao falhou (codigo $LASTEXITCODE)" }
}

# Captura stdout+stderr de um executavel sem que o PowerShell 5.1 trate o
# stderr como erro fatal (com $ErrorActionPreference = 'Stop').
function Saida-De([string]$exe, [string[]]$argumentos) {
  $anterior = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { return ((& $exe @argumentos 2>&1 | ForEach-Object { "$_" }) -join "`n") }
  finally { $ErrorActionPreference = $anterior }
}

function Baixar([string[]]$urls, [string]$destino) {
  foreach ($url in $urls) {
    try {
      Write-Host "  baixando $url"
      Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing
      if ((Get-Item $destino).Length -gt 0) { return }
    } catch {
      Write-Host "  falhou: $($_.Exception.Message)" -ForegroundColor Yellow
    }
  }
  throw "Nao foi possivel baixar $destino"
}

function Url-InstaladorTesseract {
  try {
    $cab = @{ 'User-Agent' = 'visao-ocr-pro-build' }
    if ($env:GITHUB_TOKEN) { $cab['Authorization'] = "Bearer $env:GITHUB_TOKEN" }
    $rel = Invoke-RestMethod -Headers $cab -UseBasicParsing `
      -Uri 'https://api.github.com/repos/UB-Mannheim/tesseract/releases/latest'
    $asset = $rel.assets | Where-Object { $_.name -match '^tesseract-ocr-w64-setup-.*\.exe$' } |
      Select-Object -First 1
    if ($asset) {
      Write-Host "  Tesseract mais recente: $($rel.tag_name)"
      return @($asset.browser_download_url, $TessReserva)
    }
  } catch {
    Write-Host "  API do GitHub indisponivel: $($_.Exception.Message)" -ForegroundColor Yellow
  }
  return @($TessReserva)
}

function Preparar-Tesseract {
  if (Test-Path (Join-Path $TessDir 'tesseract.exe')) {
    Write-Host "  reaproveitando $TessDir"
  } elseif ($TesseractOrigem) {
    if (-not (Test-Path (Join-Path $TesseractOrigem 'tesseract.exe'))) {
      throw "tesseract.exe nao encontrado em $TesseractOrigem"
    }
    if (Test-Path $TessDir) { Remove-Item -Recurse -Force $TessDir }
    Copy-Item -Recurse -Force $TesseractOrigem $TessDir
  } else {
    New-Item -ItemType Directory -Force $Downloads | Out-Null
    $setup = Join-Path $Downloads 'tesseract-ocr-w64-setup.exe'
    if (-not (Test-Path $setup)) { Baixar (Url-InstaladorTesseract) $setup }
    $temp = Join-Path $Build 'tesseract-extraido'
    if (Test-Path $temp) { Remove-Item -Recurse -Force $temp }
    $origem = $null

    # 1) Extrai o instalador (NSIS) com o 7-Zip: nao mexe no sistema
    $seteZip = Join-Path $env:ProgramFiles '7-Zip\7z.exe'
    if (Test-Path $seteZip) {
      # Avisos na extracao de instaladores NSIS sao comuns: quem decide e o teste abaixo
      Saida-De $seteZip @('x', $setup, "-o$temp", '-y') | Out-Null
      $exeTemp = Join-Path $temp 'tesseract.exe'
      if ((Test-Path $exeTemp) -and ((Saida-De $exeTemp @('--version')) -match 'tesseract')) { $origem = $temp }
      else { Write-Host '  extracao pelo 7-Zip nao gerou um tesseract.exe utilizavel' -ForegroundColor Yellow }
    }

    # 2) Reserva: instalacao silenciosa. O instalador usa MultiUser.nsh, que
    #    ignora o /D= e instala no caminho padrao (pode pedir administrador).
    if (-not $origem) {
      Write-Host '  instalando o Tesseract em modo silencioso...'
      Start-Process -FilePath $setup -ArgumentList '/S' -Wait
      $candidatos = @(
        (Join-Path $env:ProgramFiles 'Tesseract-OCR'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Tesseract-OCR')
      )
      $origem = $candidatos | Where-Object { Test-Path (Join-Path $_ 'tesseract.exe') } | Select-Object -First 1
    }
    if (-not $origem) { throw 'Falha ao preparar o Tesseract (use -TesseractOrigem)' }
    if (Test-Path $TessDir) { Remove-Item -Recurse -Force $TessDir }
    Copy-Item -Recurse -Force $origem $TessDir
  }

  # Idiomas: garante portugues (+ osd) e remove os demais
  $tessdata = Join-Path $TessDir 'tessdata'
  New-Item -ItemType Directory -Force $tessdata | Out-Null
  foreach ($idioma in $UrlsIdioma.Keys) {
    $arq = Join-Path $tessdata "$idioma.traineddata"
    if (-not (Test-Path $arq)) { Baixar $UrlsIdioma[$idioma] $arq }
  }
  Get-ChildItem $tessdata -Filter '*.traineddata' |
    Where-Object { $IdiomasMantidos -notcontains $_.BaseName } | Remove-Item -Force
  foreach ($pasta in @('script', 'tessdata_best', 'tessdata_fast')) {
    $p = Join-Path $tessdata $pasta
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }

  # Enxuga: so o tesseract.exe e as DLLs sao necessarios (ferramentas de treino e docs saem)
  Get-ChildItem $TessDir -Filter '*.exe' | Where-Object { $_.Name -ne 'tesseract.exe' } | Remove-Item -Force
  foreach ($item in @('doc', '$PLUGINSDIR', '$TEMP')) {
    $p = Join-Path $TessDir $item
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
  }
  Get-ChildItem $TessDir -Filter '*.html' | Remove-Item -Force
  Get-ChildItem $TessDir -Recurse -Filter '*.jar' | Remove-Item -Force   # ScrollView (depuracao)
  Get-ChildItem $TessDir -Filter 'uninstall*' | Remove-Item -Force

  $exeTess = Join-Path $TessDir 'tesseract.exe'
  $langs = Saida-De $exeTess @('--list-langs')
  if ($langs -notmatch '(?m)^por\s*$') { throw "Tesseract sem portugues: $langs" }
  $versaoTess = ((Saida-De $exeTess @('--version')) -split "`n")[0]
  $lista = ($langs -split "`r?`n" | Select-Object -Skip 1 | Where-Object { $_.Trim() }) -join ', '
  Write-Host "  $versaoTess | idiomas: $lista"
}

function Aguardar-Saude([int]$segundos) {
  $limite = (Get-Date).AddSeconds($segundos)
  while ((Get-Date) -lt $limite) {
    try { return Invoke-RestMethod -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:5002/api/ocr/health' }
    catch { Start-Sleep -Milliseconds 500 }
  }
  return $null
}

function Testar-Executavel([string]$exe, [string]$versao) {
  $pdf = Join-Path $Build 'teste-escaneado.pdf'
  Nativo { python -c "import sys; sys.path[:0] = ['tests', '.']; import test_ocr_server as t; open(sys.argv[1], 'wb').write(t.pdf_escaneado())" $pdf } 'Geracao do PDF de teste'

  $log = Join-Path $env:LOCALAPPDATA 'VisaoOCRPro\logs\servidor.log'
  $proc = Start-Process -FilePath $exe -ArgumentList '--servidor', '--sem-bandeja' -PassThru
  try {
    $saude = Aguardar-Saude 90
    if (-not $saude) { throw 'O executavel nao respondeu em /api/ocr/health' }
    Write-Host "  health: $($saude | ConvertTo-Json -Compress)"
    if ($saude.versao_app -ne $versao) { throw "versao_app = $($saude.versao_app), esperado $versao" }
    if (-not $saude.tesseract_ok -or -not $saude.idioma_ok) { throw 'Tesseract embutido sem funcionar ou sem portugues' }

    $json = curl.exe -s -F "file=@$pdf;type=application/pdf" http://127.0.0.1:5002/api/ocr/processar
    $r = $json | ConvertFrom-Json
    if ($r.paginas_ocr -ne 1 -or $r.texto -notmatch 'PROCURACAO') { throw "OCR inesperado: $json" }
    Write-Host "  OCR ok: $(($r.texto -split "`n")[1..3] -join ' / ')"

    $site = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5002/'
    if ($site.Content -notmatch 'id="root"') { throw 'O site (dist) nao foi servido' }
    $antigo = curl.exe -s -o NUL -w '%{http_code}' -X POST http://127.0.0.1:5002/api/ocr/extrato
    if ($antigo -eq '200') { throw 'Rota de extrato ainda responde' }
    Write-Host '  executavel congelado OK' -ForegroundColor Green
  } catch {
    if (Test-Path $log) { Write-Host '---- servidor.log ----'; Get-Content $log -Tail 80 }
    throw
  } finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Get-Process tesseract -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  }
}

function Achar-ISCC {
  $candidatos = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
  )
  foreach ($c in $candidatos) { if ($c -and (Test-Path $c)) { return $c } }
  $cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  if (Get-Command choco -ErrorAction SilentlyContinue) {
    Write-Host '  instalando Inno Setup via Chocolatey...'
    Nativo { choco install innosetup -y --no-progress | Out-Null } 'Instalacao do Inno Setup'
    foreach ($c in $candidatos) { if ($c -and (Test-Path $c)) { return $c } }
  }
  throw 'Inno Setup 6 nao encontrado. Instale em https://jrsoftware.org/isdl.php'
}

# ============================================================================
Push-Location $Raiz
try {
  $Versao = (python -c "from versao import VERSAO_APP; print(VERSAO_APP)").Trim()
  if ($LASTEXITCODE -ne 0 -or -not $Versao) { throw 'Python nao encontrado no PATH' }
  Write-Host "Visao OCR Pro $Versao" -ForegroundColor Green
  New-Item -ItemType Directory -Force $Build, $Saida | Out-Null

  Etapa '1/7 Site (npm ci + build)'
  Nativo { npm ci --no-audit --no-fund } 'npm ci'
  Nativo { npm run lint } 'Verificacao de tipos (tsc)'
  Nativo { npm run build } 'npm run build'

  Etapa '2/7 Tesseract portatil com portugues'
  Preparar-Tesseract

  if (-not $PularTestes) {
    Etapa '3/7 Testes automatizados'
    $pathAntigo = $env:PATH
    $env:PATH = "$TessDir;$env:PATH"
    $env:TESSDATA_PREFIX = Join-Path $TessDir 'tessdata'
    try { Nativo { python -m pytest -q -p no:cacheprovider tests } 'Testes (pytest)' }
    finally { $env:PATH = $pathAntigo; Remove-Item Env:TESSDATA_PREFIX -ErrorAction SilentlyContinue }
  }

  Etapa '4/7 PyInstaller'
  if (Test-Path $Pacote) { Remove-Item -Recurse -Force $Pacote }
  Nativo { python -m PyInstaller --noconfirm --clean `
      --distpath (Join-Path $Build 'pacote') --workpath (Join-Path $Build 'pyinstaller') `
      instalador\VisaoOCRPro.spec } 'PyInstaller'
  Copy-Item -Recurse -Force (Join-Path $Raiz 'dist') (Join-Path $Pacote 'dist')
  Copy-Item -Recurse -Force $TessDir (Join-Path $Pacote 'Tesseract-OCR')
  Copy-Item -Force (Join-Path $PSScriptRoot 'LEIA-ME.txt') $Pacote

  if (-not $PularTestes) {
    Etapa '5/7 Teste do executavel congelado'
    Testar-Executavel (Join-Path $Pacote 'VisaoOCRPro.exe') $Versao
  }

  if (-not $SemInstalador) {
    Etapa '6/7 Instalador (Inno Setup)'
    $iscc = Achar-ISCC
    Nativo { & $iscc /Q "/DMyAppVersion=$Versao" "/DPacoteDir=$Pacote" "/O$Saida" `
        (Join-Path $PSScriptRoot 'VisaoOCRPro.iss') } 'Inno Setup'
  }

  Etapa '7/7 ZIP portatil'
  $zip = Join-Path $Saida "VisaoOCRPro-$Versao-portatil.zip"
  if (Test-Path $zip) { Remove-Item -Force $zip }
  Compress-Archive -Path $Pacote -DestinationPath $zip -CompressionLevel Optimal

  Etapa 'Pronto'
  $somas = Join-Path $Saida 'SHA256SUMS.txt'
  if (Test-Path $somas) { Remove-Item -Force $somas }
  $arquivos = @(Get-ChildItem $Saida -File | Where-Object { $_.Name -like "VisaoOCRPro*$Versao*" })
  foreach ($a in $arquivos) {
    $hash = (Get-FileHash $a.FullName -Algorithm SHA256).Hash
    "{0}  {1}" -f $hash, $a.Name | Add-Content $somas
    Write-Host ("  {0}  ({1:N1} MB)" -f $a.Name, ($a.Length / 1MB))
  }
} finally {
  Pop-Location
}
