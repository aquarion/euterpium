#define MyAppName "Euterpium"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef ReleaseTag
  #define ReleaseTag "v" + AppVersion
#endif

[Setup]
AppId={{B2C48E1C-6E56-4FE9-B1EF-47A643FE53D4}}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher=aquarion
DefaultDirName={localappdata}\Programs\Euterpium
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=euterpium-{#ReleaseTag}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\euterpium.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\euterpium\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\euterpium.exe"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\euterpium.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\euterpium.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
