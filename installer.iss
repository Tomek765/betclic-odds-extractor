#define MyAppName "APEX Context Engine"
#define MyAppVersion "1.0.0"
#define MyAppExeName "APEX_Context_Engine.exe"

[Setup]
AppId={{9E8E4E83-93C8-42D7-AE67-F65D6F5274BD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=APEX
DefaultDirName={localappdata}\Programs\APEX Context Engine
DefaultGroupName=APEX Context Engine
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer_output
OutputBaseFilename=APEX_Context_Engine_Setup_Win64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

[Files]
Source: "dist\APEX_Context_Engine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README_START_PL.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\APEX Context Engine"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\APEX Context Engine"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Uruchom APEX Context Engine"; Flags: nowait postinstall skipifsilent
