; Inno Setup 7 (recommended, e.g. 7.0.2) or 6 — builds CuePlayer-Setup-<version>.exe
; Requires: packaging\build_windows.ps1 already produced dist\CuePlayer\
; Compile:  iscc /DMyAppVersion=1.0.5 packaging\CuePlayer.iss
; Download: https://jrsoftware.org/isdl.php  (you build; employees only get Setup.exe)

#ifndef MyAppVersion
  #define MyAppVersion "1.0.5"
#endif

#define MyAppName "CuePlayer"
#define MyAppPublisher "CuePlayer"
#define MyAppExeName "CuePlayer.exe"
#define MyAppURL "https://github.com/zillawillysu-a11y/CuePlayer_didido"

[Setup]
AppId={{A8F3C2E1-5B7D-4E9A-9C1F-2D6B8A0E4F31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=CuePlayer-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=cueplayer.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Entire PyInstaller onedir folder
Source: "..\dist\CuePlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
