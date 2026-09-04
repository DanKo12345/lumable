#define MyAppName "LumaBLE"
#ifndef MyAppVersion
#define MyAppVersion "0.4.3"
#endif
#ifndef MyAppId
#define MyAppId "{{9F04E5C5-2B4B-43E4-A0E8-2CB916B0E8E8}"
#endif
#ifndef MyPrivilegesRequired
#define MyPrivilegesRequired "admin"
#endif
#ifndef MyUserDataDir
#define MyUserDataDir "{userappdata}\LumaBLE"
#endif
#define MyAppPublisher "dollza"
#define MyAppExeName "LumaBLE.exe"

[Setup]
AppId={#MyAppId}
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
PrivilegesRequired={#MyPrivilegesRequired}
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
english.LicenceBeforeRemoval=If a Pro licence is activated on this computer, releasing it first is important: removing the saved data leaves the activation slot taken, and the key cannot then be used on another computer.%n%nTo release it, stop here, open LumaBLE, use Transfer licence, and then uninstall.%n%nYes - stop, so the licence can be released first%nNo - remove now, without releasing anything
russian.LicenceBeforeRemoval=Если на этом компьютере активирована Pro-лицензия, её важно сначала отвязать: при удалении сохранённых данных место активации останется занятым, и ключ нельзя будет использовать на другом компьютере.%n%nЧтобы отвязать, прервите удаление, откройте LumaBLE, воспользуйтесь переносом лицензии и удалите программу после этого.%n%nДа — прервать, чтобы сначала отвязать лицензию%nНет — удалить сейчас, ничего не отвязывая

[UninstallDelete]
Type: filesandordirs; Name: "{#MyUserDataDir}"; Check: ShouldRemoveUserData

[Code]
{
  Removing the user data folder destroys the installation identity a Pro licence
  is bound to. That does not free the activation slot - it makes it
  unreclaimable, because the identity was the one thing that could have said
  which slot was ours. The person then cannot use their key on a new computer.

  The uninstaller cannot fix this itself, and two separate limits say so.

  It cannot run LumaBLE to do the work: ExecAsOriginalUser is documented as not
  supported at uninstall time. An earlier version of this script called it
  anyway, which would have failed on every real uninstall.

  It cannot even tell whether a licence is active. It runs elevated, so
  %APPDATA% is the administrator's profile rather than the profile holding
  the settings - the same reason the first point is true.

  So it does the one thing it can do honestly: says what is at stake, and lets
  the person go and do it themselves. The warning is worded as a condition
  because this script genuinely does not know, and pretending otherwise would
  be inventing a fact about somebody's licence.
}

var
  RemoveUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  { A silent uninstall cannot ask what to do. Preserve the identity and licence
    state; an administrator can remove those files explicitly if required. }
  if UninstallSilent then
  begin
    RemoveUserData := False;
    Result := True;
    Exit;
  end;

  RemoveUserData := MsgBox(
    CustomMessage('RemoveUserDataPrompt'),
    mbConfirmation,
    MB_YESNO or MB_DEFBUTTON2
  ) = IDYES;

  Result := True;
  if not RemoveUserData then
    { Keeping the data keeps the identity, so a licence survives a reinstall and
      there is nothing at stake. }
    Exit;

  { Default is the safe one: stop, so somebody who is not reading carefully does
    not lose a purchase to a keypress. }
  if MsgBox(CustomMessage('LicenceBeforeRemoval'), mbInformation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    Result := False;
end;

function ShouldRemoveUserData(): Boolean;
begin
  Result := RemoveUserData;
end;
