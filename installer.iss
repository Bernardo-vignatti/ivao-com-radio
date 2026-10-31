; Instalador do COM Radio. O build.bat compila isto depois do PyInstaller;
; a saida e dist\COM-Radio-Setup-<versao>.exe.
;
; Instala em Arquivos de Programas, cria os atalhos, libera o app no firewall
; do Windows na rede privada (sem isso o iPhone nao alcanca o PC) e instala o
; WebView2 da Microsoft se faltar, que e o que desenha a janela do PC.

#define AppName "COM Radio"
; a mesma versao de VERSION em app/gui.py
#define AppVersion "2.1.0"
#define AppExe "COM Radio.exe"

[Setup]
AppId={{8B2F7C1E-5C3A-4F7E-9A51-2D6C0B7E4A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Bernardo Vignatti
AppPublisherURL=https://github.com/Bernardo-vignatti/ivao-com-radio
AppSupportURL=https://github.com/Bernardo-vignatti/ivao-com-radio/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=COM-Radio-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; o app cria este mutex: o instalador pede para fechar antes de mexer nos arquivos
AppMutex=COMRadio.Instance

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "dist\COM Radio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; apaga antes de criar, para reinstalar nao duplicar a regra
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private"; Flags: runhidden; StatusMsg: "Liberando o COM Radio no firewall do Windows..."
; sem skipifsilent: a atualizacao pelo app roda o instalador com /SILENT e
; o app precisa reabrir sozinho no fim. postinstall roda como o usuario, nao admin
Filename: "{app}\{#AppExe}"; Description: "Abrir o COM Radio"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; RunOnceId: "firewall"

[Code]
const
  WebView2Key = '\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Url = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';

var
  DownloadPage: TDownloadWizardPage;

function HasVersion(Root: Integer; Key: String): Boolean;
var
  V: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', V) and (V <> '') and (V <> '0.0.0.0');
end;

function WebView2Installed: Boolean;
begin
  Result := HasVersion(HKLM, 'SOFTWARE\WOW6432Node' + WebView2Key)
    or HasVersion(HKLM, 'SOFTWARE' + WebView2Key)
    or HasVersion(HKCU, 'Software' + WebView2Key);
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), 'Baixando o WebView2 da Microsoft...', nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: Integer;
begin
  Result := True;
  if (CurPageID <> wpReady) or WebView2Installed then
    Exit;
  DownloadPage.Clear;
  DownloadPage.Add(WebView2Url, 'MicrosoftEdgeWebview2Setup.exe', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      DownloadPage.SetText('Instalando o WebView2 da Microsoft...', '');
      Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code);
    except
      MsgBox('Não foi possível instalar o WebView2 da Microsoft, que desenha a janela do COM Radio.' + #13#10#13#10 +
        'A instalação continua. Se a janela não abrir, instale o "Microsoft Edge WebView2 Runtime" pelo site da Microsoft.',
        mbInformation, MB_OK);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  // o Iniciar com o Windows e gravado pelo proprio app
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
  if UninstallSilent then
    Exit;
  if MsgBox('Apagar também as configurações e o certificado do COM Radio?' + #13#10#13#10 +
      'Se apagar, numa próxima instalação será preciso instalar o certificado no iPhone de novo.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(ExpandConstant('{userappdata}\{#AppName}'), True, True, True);
end;
