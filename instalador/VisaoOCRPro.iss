; ============================================================================
;  Visão OCR Pro — instalador (Inno Setup 6)
;  Gerado por instalador/build.ps1. Compilação manual:
;    ISCC /DMyAppVersion=3.0.0 /DPacoteDir=..\build\pacote\VisaoOCRPro VisaoOCRPro.iss
;
;  - Instala por usuário (sem administrador) em
;    %LOCALAPPDATA%\Programs\VisaoOCRPro — a mesma pasta da versão 2.0.
;  - Antes de instalar, encerra o servidor em execução e remove versões
;    antigas do Visão OCR Pro (inclusive a 2.0, com extrato e maquininha).
;  - Pacote completo: servidor congelado + site + Tesseract com português.
; ============================================================================

#define MyAppName "Visão OCR Pro"
#ifndef MyAppVersion
  #define MyAppVersion "3.0.0"
#endif
#ifndef PacoteDir
  #define PacoteDir "..\build\pacote\VisaoOCRPro"
#endif
#define MyAppExe "VisaoOCRPro.exe"
#define MyAppPublisher "Marques & Gameiro Advocacia"

[Setup]
AppId={{B014BFF1-7E2C-4819-B6FE-671722F5C978}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VisaoOCRPro
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\saida
OutputBaseFilename=VisaoOCRPro-Setup-{#MyAppVersion}
SetupIconFile=visao-ocr-pro.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Instalador do {#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
CloseApplications=yes
SetupLogging=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
brazilianportuguese.WelcomeLabel2=Este assistente vai instalar o [name/ver] neste computador.%n%nVersão somente OCR: o Tesseract (com português) já vem incluído — não é preciso instalar Python nem Tesseract.%n%nSe houver uma versão anterior do Visão OCR Pro, ela será removida automaticamente.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "iniciarwindows"; Description: "Deixar o servidor OCR pronto ao ligar o computador (abre mais rápido)"; GroupDescription: "Opções:"; Flags: unchecked

[InstallDelete]
; Restos da versão 2.0 (extrato bancário e maquininha) e do pacote anterior
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\dist"
Type: filesandordirs; Name: "{app}\Tesseract-OCR"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\extrato_parser*"
Type: files; Name: "{app}\vendas_cartao*"
Type: files; Name: "{app}\exportar_dataset_apuracao*"
Type: files; Name: "{app}\IniciarVisaoOCRPro.*"

[Files]
Source: "{#PacoteDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autoprograms}\{#MyAppName} — Processar pasta de PDFs"; Filename: "{app}\{#MyAppExe}"; Parameters: "--processar-pasta"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Parameters: "--servidor"; Tasks: iniciarwindows

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM {#MyAppExe}"; Flags: runhidden; RunOnceId: "EncerrarVisaoOCRPro"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\dist"
Type: filesandordirs; Name: "{app}\Tesseract-OCR"

[Code]
const
  CHAVE_UNINSTALL = 'Software\Microsoft\Windows\CurrentVersion\Uninstall';
  NOSSA_CHAVE = '{B014BFF1-7E2C-4819-B6FE-671722F5C978}_is1';

{ "Visão OCR Pro", "Visao OCR Pro", "VisaoOCRPro"... }
function EhVisaoOcrPro(const Nome: String): Boolean;
var
  N: String;
begin
  N := Lowercase(Nome);
  StringChangeEx(N, ' ', '', True);
  Result := (Pos('vis', N) = 1) and (Pos('ocrpro', N) > 0);
end;

{ Separa '"C:\...\unins000.exe" /ARG' em executável e argumentos }
procedure SepararComando(const Linha: String; var Exe, Args: String);
var
  S: String;
  P: Integer;
begin
  S := Trim(Linha);
  Exe := S;
  Args := '';
  if (Length(S) > 0) and (S[1] = '"') then
  begin
    Delete(S, 1, 1);
    P := Pos('"', S);
    if P > 0 then
    begin
      Exe := Copy(S, 1, P - 1);
      Args := Trim(Copy(S, P + 1, Length(S)));
    end
    else
      Exe := S;
  end
  else
  begin
    P := Pos('.exe', Lowercase(S));
    if P > 0 then
    begin
      Exe := Copy(S, 1, P + 3);
      Args := Trim(Copy(S, P + 4, Length(S)));
    end;
  end;
end;

procedure DesinstalarVersoesAntigas(Raiz: Integer; const NomeRaiz: String);
var
  Chaves: TArrayOfString;
  I, Codigo: Integer;
  Chave, Nome, Comando, Exe, Args: String;
begin
  if not RegGetSubkeyNames(Raiz, CHAVE_UNINSTALL, Chaves) then
    Exit;
  for I := 0 to GetArrayLength(Chaves) - 1 do
  begin
    Chave := Chaves[I];
    if CompareText(Chave, NOSSA_CHAVE) = 0 then
      Continue;
    if not RegQueryStringValue(Raiz, CHAVE_UNINSTALL + '\' + Chave, 'DisplayName', Nome) then
      Continue;
    if not EhVisaoOcrPro(Nome) then
      Continue;
    if not RegQueryStringValue(Raiz, CHAVE_UNINSTALL + '\' + Chave, 'UninstallString', Comando) then
      Continue;
    SepararComando(Comando, Exe, Args);
    if not FileExists(Exe) then
    begin
      Log(Format('Versão antiga "%s" sem desinstalador em %s', [Nome, Exe]));
      Continue;
    end;
    if CompareText(Copy(Chave, Length(Chave) - 3, 4), '_is1') = 0 then
      Args := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'  { Inno Setup }
    else
      Args := Trim(Args + ' /S');                        { NSIS e outros }
    Log(Format('Removendo versão antiga "%s" (%s): %s %s', [Nome, NomeRaiz, Exe, Args]));
    if ShellExec('', Exe, Args, '', SW_HIDE, ewWaitUntilTerminated, Codigo) then
      Log(Format('Desinstalador antigo terminou com código %d', [Codigo]))
    else
      Log('Falha ao executar o desinstalador antigo: ' + SysErrorMessage(Codigo));
  end;
end;

procedure EncerrarProcessos;
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#MyAppExe}', '', SW_HIDE,
    ewWaitUntilTerminated, Codigo);
  { Versão 2.0 rodando pelo código-fonte (pythonw + waitress ocr_server:app) }
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | ' +
    'Where-Object { $_.CommandLine -like ''*ocr_server*'' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    '', SW_HIDE, ewWaitUntilTerminated, Codigo);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  EncerrarProcessos;
  DesinstalarVersoesAntigas(HKCU, 'HKCU');
  DesinstalarVersoesAntigas(HKLM32, 'HKLM32');
  if IsWin64 then
    DesinstalarVersoesAntigas(HKLM64, 'HKLM64');
  Result := '';
end;
