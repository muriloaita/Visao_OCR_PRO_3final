<#
.SYNOPSIS
  Teste de ponta a ponta do Setup gerado: instala em modo silencioso, confere
  a limpeza dos restos da versao 2.0, abre o app, faz OCR e desinstala.
  Usado pelo GitHub Actions depois do build.ps1.
#>
param([Parameter(Mandatory = $true)][string]$Setup)

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent $PSScriptRoot
$App = Join-Path $env:LOCALAPPDATA 'Programs\VisaoOCRPro'
$Exe = Join-Path $App 'VisaoOCRPro.exe'

function Aguardar-Saude([int]$segundos) {
  $limite = (Get-Date).AddSeconds($segundos)
  while ((Get-Date) -lt $limite) {
    try { return Invoke-RestMethod -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:5002/api/ocr/health' }
    catch { Start-Sleep -Milliseconds 500 }
  }
  return $null
}

# Simula restos da versao 2.0 na mesma pasta (extrato e maquininha)
New-Item -ItemType Directory -Force (Join-Path $App '_internal') | Out-Null
Set-Content (Join-Path $App 'extrato_parser.py') 'resto da versao 2.0'
Set-Content (Join-Path $App 'vendas_cartao.py') 'resto da versao 2.0'
Set-Content (Join-Path $App '_internal\velho.txt') 'resto da versao 2.0'

Write-Host "Instalando $Setup ..."
$log = Join-Path $env:TEMP 'visao-setup.log'
$p = Start-Process -FilePath $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$log" -Wait -PassThru
if ($p.ExitCode -ne 0) { Get-Content $log -Tail 60; throw "Setup terminou com codigo $($p.ExitCode)" }

foreach ($f in @($Exe, "$App\dist\index.html", "$App\Tesseract-OCR\tesseract.exe",
                 "$App\Tesseract-OCR\tessdata\por.traineddata", "$App\unins000.exe")) {
  if (-not (Test-Path $f)) { throw "Arquivo ausente apos instalar: $f" }
}
foreach ($f in @("$App\extrato_parser.py", "$App\vendas_cartao.py", "$App\_internal\velho.txt")) {
  if (Test-Path $f) { throw "Resto da versao antiga nao foi removido: $f" }
}
$atalho = Join-Path ([Environment]::GetFolderPath('Programs')) 'Visão OCR Pro.lnk'
if (-not (Test-Path $atalho)) { throw "Atalho do Menu Iniciar ausente: $atalho" }
Write-Host 'Instalacao OK (arquivos, atalhos e limpeza da versao antiga)' -ForegroundColor Green

$pdf = Join-Path $env:TEMP 'teste-instalador.pdf'
Push-Location $Raiz
try { python -c "import sys; sys.path[:0] = ['tests', '.']; import test_ocr_server as t; open(sys.argv[1], 'wb').write(t.pdf_escaneado())" $pdf }
finally { Pop-Location }

$proc = Start-Process -FilePath $Exe -ArgumentList '--servidor', '--sem-bandeja' -PassThru
try {
  $saude = Aguardar-Saude 90
  if (-not $saude -or -not $saude.idioma_ok) { throw "App instalado nao respondeu corretamente: $($saude | ConvertTo-Json -Compress)" }
  $r = curl.exe -s -F "file=@$pdf;type=application/pdf" http://127.0.0.1:5002/api/ocr/processar | ConvertFrom-Json
  if ($r.texto -notmatch 'PROCURACAO') { throw "OCR do app instalado falhou: $($r | ConvertTo-Json -Compress)" }
  Write-Host 'App instalado OK (servidor + OCR em portugues)' -ForegroundColor Green
} finally {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

Write-Host 'Desinstalando...'
$u = Start-Process -FilePath (Join-Path $App 'unins000.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
# O desinstalador do Inno se copia para a pasta temporaria e termina por la
$limite = (Get-Date).AddSeconds(60)
while ((Test-Path $Exe) -and ((Get-Date) -lt $limite)) { Start-Sleep -Milliseconds 500 }
if (Test-Path $Exe) { throw 'O desinstalador nao removeu o VisaoOCRPro.exe' }
if (Test-Path $atalho) { throw "O desinstalador nao removeu o atalho: $atalho" }
Write-Host "Desinstalacao OK (codigo $($u.ExitCode))" -ForegroundColor Green
