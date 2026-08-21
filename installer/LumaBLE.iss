#define MyAppName "LumaBLE"
#define MyAppVersion "0.4.0"
#define MyAppPublisher "dollza"
#define MyAppExeName "LumaBLE.exe"

[Setup]
AppId={{9F04E5C5-2B4B-43E4-A0E8-2CB916B0E8E8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=LumaBLE-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; LumaBLE needs Qt 6 + WinRT Bluetooth, which require Windows 10 or newer.
; Refuse to install on older Windows instead of failing to launch afterwards.
MinVersion=10.0
SetupIconFile=..\app\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\LumaBLE\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; A PyInstaller update replaces the complete bundled runtime. Removing the old
; internal directory first prevents obsolete Qt/Python files surviving upgrades.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#MyAppExeName}"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[CustomMessages]
english.RemoveUserDataPrompt=Remove saved LumaBLE settings, profiles, licence state, and diagnostics too?%n%nChoose No to keep them for a future reinstall.
russian.RemoveUserDataPrompt=Удалить также сохранённые настройки, профили, состояние лицензии и диагностику LumaBLE?%n%nВыберите «Нет», чтобы сохранить их для будущей установки.

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\LumaBLE"; Check: ShouldRemoveUserData

[Code]
var
  RemoveUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  RemoveUserData := MsgBox(
    CustomMessage('RemoveUserDataPrompt'),
    mbConfirmation,
    MB_YESNO or MB_DEFBUTTON2
  ) = IDYES;
  Result := True;
end;

function ShouldRemoveUserData(): Boolean;
begin
  Result := RemoveUserData;
end;
