; ClawBridge Inno Setup Installer Script
; ========================================
; Requires: Inno Setup 6+ (https://jrsoftware.org/isdl.php)
; Build:    ISCC.exe installer.iss
;           or:  python build.py --inno
;
; Expects dist\ClawBridge\ to exist (run build.py first).

#define MyAppName "ClawBridge"
#define MyAppVersion "0.5.1"
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
OutputBaseFilename=ClawBridge-Setup
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
; Only the final "Launch" checkbox — all heavy work is done in [Code] with progress bar
Filename: "{app}\ClawBridge.bat"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runhidden runasoriginaluser

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

    Choice := MsgBox('ClawBridge ' + InstalledVer + ' is already installed.' + #13#10 + #13#10 +
              'What would you like to do?' + #13#10 + #13#10 +
              '  YES = Uninstall existing version, then reinstall' + #13#10 +
              '  NO = Upgrade in place (keep existing installation)' + #13#10 +
              '  CANCEL = Exit installer' + #13#10 + #13#10 +
              'Note: Your .env settings and workspace data will be preserved.',
              mbConfirmation, MB_YESNOCANCEL);

    if Choice = IDCANCEL then
    begin
      Result := False;
      Exit;
    end
    else if Choice = IDYES then
    begin
      if not Exec(RemoveQuotes(UninstallStr), '/SILENT /NORESTART', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      begin
        MsgBox('Failed to run uninstaller. Please uninstall manually from Add/Remove Programs.', mbError, MB_OK);
        Result := False;
        Exit;
      end;
      Sleep(1500);
    end;
  end;
end;

// ── Post-install with progress bar ──────────────────────────────────────
procedure RunWithProgress(const Exe, Params, WorkDir, StepLabel: String;
  ProgressPage: TOutputProgressWizardPage; StepPct, TotalSteps: Integer);
var
  ResultCode: Integer;
begin
  ProgressPage.SetText(StepLabel, 'This may take a few minutes...');
  ProgressPage.SetProgress(StepPct, TotalSteps);
  ProgressPage.Show;
  Exec(Exe, Params, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ProgressPage: TOutputProgressWizardPage;
  AppDir: String;
  TotalSteps: Integer;
  CurrentStep: Integer;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir := ExpandConstant('{app}');

    // Create .env from .env.example if it doesn't exist
    if not FileExists(AppDir + '\.env') then
    begin
      if FileExists(AppDir + '\.env.example') then
        CopyFile(AppDir + '\.env.example', AppDir + '\.env', False);
    end;

    // Determine total steps based on tasks
    TotalSteps := 100;
    CurrentStep := 0;

    // Create progress page
    ProgressPage := CreateOutputProgressPage(
      'Configuring ClawBridge',
      'Setting up engines and browser automation...');

    try
      ProgressPage.Show;

      // Step 1: Verify Python works (5%)
      ProgressPage.SetText('Verifying embedded Python...', '');
      ProgressPage.SetProgress(5, TotalSteps);
      Exec(AppDir + '\python\python.exe', '--version', AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);

      // Step 2: Install Playwright Chromium (5% -> 70%)
      ProgressPage.SetText('Installing Playwright Chromium browser...', 'Downloading browser engine — this may take 1-3 minutes.');
      ProgressPage.SetProgress(10, TotalSteps);
      Exec(AppDir + '\python\python.exe', '-m playwright install chromium', AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
      ProgressPage.SetProgress(70, TotalSteps);

      // Step 3 (optional): Install OpenClaw
      if WizardIsTaskSelected('installopenclaw') then
      begin
        ProgressPage.SetText('Installing OpenClaw engine...', 'Installing via npm — this may take 1-2 minutes.');
        ProgressPage.SetProgress(75, TotalSteps);
        Exec(AppDir + '\install_openclaw.bat', '', AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
        ProgressPage.SetProgress(95, TotalSteps);
      end
      else
      begin
        ProgressPage.SetProgress(95, TotalSteps);
      end;

      // Step 4: Create workspace directories
      ProgressPage.SetText('Creating workspace...', 'Almost done!');
      ProgressPage.SetProgress(98, TotalSteps);
      ForceDirectories(AppDir + '\workspace');
      ForceDirectories(AppDir + '\workspace\memory');
      ForceDirectories(AppDir + '\workspace\templates');
      ForceDirectories(AppDir + '\workspace\schedules');
      ForceDirectories(AppDir + '\workspace\workflows');
      ForceDirectories(AppDir + '\logs');

      // Done
      ProgressPage.SetText('Setup complete!', 'ClawBridge is ready to use.');
      ProgressPage.SetProgress(100, TotalSteps);
      Sleep(800);

    finally
      ProgressPage.Hide;
    end;
  end;
end;
