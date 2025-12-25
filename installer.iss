; AutoMouse Inno Setup Script
; Creates a Windows installer for AutoMouse
;
; Requirements:
;   - Inno Setup 6: https://jrsoftware.org/isinfo.php
;   - Run build_windows.py first to create the Nuitka build
;
; Usage:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define MyAppName "AutoMouse"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AutoMouse"
#define MyAppURL "https://github.com/yourusername/automouse"
#define MyAppExeName "AutoMouse.exe"

[Setup]
; Unique ID for this application (generate new GUID for your app)
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Install location
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}

; Output settings
OutputDir=dist
OutputBaseFilename=AutoMouse-{#MyAppVersion}-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; Compression (solid compression is smaller but can trigger some AV)
Compression=lzma2
SolidCompression=no

; Privileges (don't require admin if possible)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Modern installer look
WizardStyle=modern

; Signing (uncomment if you have a code signing certificate)
; SignTool=signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a $f

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start AutoMouse when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Main application files from Nuitka build
Source: "dist\automouse.__main__.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Note: Adjust the source path if your Nuitka output directory is different

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Add to startup if selected
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Try to stop the app before uninstalling
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
// Check if app is running before install/uninstall
function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('tasklist', '/FI "IMAGENAME eq {#MyAppExeName}" /NH', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if IsAppRunning() then
  begin
    if MsgBox('{#MyAppName} is currently running. Setup will attempt to close it. Continue?',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
    end;
  end;
end;
