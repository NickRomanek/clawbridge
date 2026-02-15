; ClawBridge Inno Setup Installer Script
; ========================================
; Requires: Inno Setup 6+ (https://jrsoftware.org/isdl.php)
; Build:    ISCC.exe installer.iss
;           or:  python build.py --inno
;
; Expects dist\ClawBridge\ to exist (run build.py first).

#define MyAppName "ClawBridge"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "ClawBridge"
#define MyAppURL "https://clawbridge.ai"
#define MyAppExeName "ClawBridge.bat"

[Setup]
AppId={{B7C3E4F5-A1D2-4E6F-8B9C-0D1E2F3A4B5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output installer to dist/
OutputDir=dist
OutputBaseFilename=ClawBridge-Setup-{#MyAppVersion}
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Require Windows 10+
MinVersion=10.0
; Admin not required (installs to user folder by default)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Appearance
WizardStyle=modern
SetupIconFile=clawbridge.ico
; Uninstall
UninstallDisplayIcon={app}\clawbridge.ico
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startuptask"; Description: "Start ClawBridge when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked
Name: "installopenclaw"; Description: "Install OpenClaw AI engine (adds memory && skills support, can also install later from dashboard)"; GroupDescription: "Optional Engines:"; Flags: unchecked

[Files]
; Bundle everything from the portable build
Source: "dist\ClawBridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\ClawBridge"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\clawbridge.ico"; Comment: "Launch ClawBridge dashboard"
Name: "{group}\ClawBridge (Console)"; Filename: "{app}\run.bat"; WorkingDir: "{app}"; IconFilename: "{app}\clawbridge.ico"; Comment: "Launch ClawBridge with console output"
Name: "{group}\Update Dependencies"; Filename: "{app}\update.bat"; WorkingDir: "{app}"; Comment: "Update ClawBridge dependencies"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
; Desktop shortcut (optional)
Name: "{autodesktop}\ClawBridge"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\clawbridge.ico"; Tasks: desktopicon
; Startup entry (optional)
Name: "{userstartup}\ClawBridge"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startuptask

[Run]
; Install Playwright Chromium to default location (ensures it works even if bundled path fails)
Filename: "{app}\python\python.exe"; Parameters: "-m playwright install chromium"; WorkingDir: "{app}"; StatusMsg: "Installing Playwright Chromium browser (this may take a moment)..."; Flags: runhidden waituntilterminated
; Install OpenClaw via bundled Node.js (optional task, runs before launch)
Filename: "{app}\install_openclaw.bat"; WorkingDir: "{app}"; StatusMsg: "Installing OpenClaw engine (this may take a moment)..."; Tasks: installopenclaw; Flags: runhidden waituntilterminated
; Offer to launch after install - uses ClawBridge.bat which opens loading page instantly then starts the app
Filename: "{app}\ClawBridge.bat"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runhidden

[UninstallDelete]
; Clean up generated files on uninstall
Type: filesandordirs; Name: "{app}\workspace"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\nodejs\node_modules"
Type: files; Name: "{app}\clawbridge.db"
Type: files; Name: "{app}\clawbridge.id"
Type: files; Name: "{app}\.env"

[Code]
// ── Previous install detection & uninstall ──────────────────────────────
function GetUninstallString(): String;
var
  UninstallPath: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1',
    'UninstallString', UninstallPath) then
    Result := UninstallPath
  else if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1',
    'UninstallString', UninstallPath) then
    Result := UninstallPath;
end;

function GetInstalledVersion(): String;
var
  InstalledVersion: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1',
    'DisplayVersion', InstalledVersion) then
    Result := InstalledVersion
  else if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1',
    'DisplayVersion', InstalledVersion) then
    Result := InstalledVersion;
end;

function InitializeSetup(): Boolean;
var
  UninstallStr: String;
  InstalledVer: String;
  ResultCode: Integer;
  Choice: Integer;
begin
  Result := True;
  UninstallStr := GetUninstallString();

  if UninstallStr <> '' then
  begin
    InstalledVer := GetInstalledVersion();

    // Show a task dialog with clear options
    Choice := MsgBox('ClawBridge ' + InstalledVer + ' is already installed.' + #13#10 + #13#10 +
              'What would you like to do?' + #13#10 + #13#10 +
              '  YES = Uninstall existing version, then reinstall' + #13#10 +
              '  NO = Upgrade in place (keep existing installation)' + #13#10 +
              '  CANCEL = Exit installer' + #13#10 + #13#10 +
              'Note: Your .env settings and workspace data will be preserved.',
              mbConfirmation, MB_YESNOCANCEL);

    if Choice = IDCANCEL then
    begin
      Result := False;  // Exit installer
      Exit;
    end
    else if Choice = IDYES then
    begin
      // Run the uninstaller
      if not Exec(RemoveQuotes(UninstallStr), '/SILENT /NORESTART', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      begin
        MsgBox('Failed to run uninstaller. Please uninstall manually from Add/Remove Programs.', mbError, MB_OK);
        Result := False;
        Exit;
      end;
      // Small delay to let uninstaller release files
      Sleep(1500);
    end;
    // If NO, continue with upgrade in place
  end;
end;

// ── Post-install: create .env from template ─────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Create .env from .env.example if it doesn't exist
    if not FileExists(ExpandConstant('{app}\.env')) then
    begin
      if FileExists(ExpandConstant('{app}\.env.example')) then
        CopyFile(ExpandConstant('{app}\.env.example'), ExpandConstant('{app}\.env'), False);
    end;
  end;
end;
