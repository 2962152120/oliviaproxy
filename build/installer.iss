; Olivia 来信拦截助手 - Inno Setup 安装脚本
#define MyAppName "Olivia 来信拦截助手"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "OliviaProxy"
#define MyAppExeName "OliviaGUI.exe"
#define SrcDir "D:\OliviaProxy\release\OliviaProxy"

[Setup]
AppId={{8A1E3C4D-6B52-4F5A-9C7D-3E2F1B0A9D8C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\OliviaProxy
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=D:\OliviaProxy\release
OutputBaseFilename=OliviaProxy-Setup-1.0.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
CloseApplications=yes
SetupIconFile=icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional tasks:"
Name: "runnow"; Description: "Launch after installation"; GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
Source: "{#SrcDir}\OliviaGUI.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\olivia_letter_proxy.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\start.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\uninstall.bat"; DestDir: "{app}"; Flags: ignoreversion
; 自包含运行时
Source: "{#SrcDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; Tasks: runnow

[UninstallRun]
Filename: "{app}\uninstall.bat"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\letters.json"
Type: filesandordirs; Name: "{app}\debug.log"
Type: filesandordirs; Name: "{app}\proxy_backup.txt"