; CheapTrader installer (Inno Setup 6.3 or newer: https://jrsoftware.org/isinfo.php).
;
; Build, after  cd backend ; uv run python scripts/build_exe.py --onefile --public --out ../dist-release :
;
;     ISCC.exe /DAppVersion=0.1.0 installer\CheapTrader.iss
;
; The release workflow (.github/workflows/release.yml) does exactly this. The installer needs no
; administrator rights: it installs for the current user. Uninstalling leaves the data folder
; (drawings, saved settings, bar history) where it is.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{05F8DEF8-687E-44E0-BB4D-9C8F5C095BB7}
AppName=CheapTrader
AppVersion={#AppVersion}
AppVerName=CheapTrader {#AppVersion}
AppPublisher=CheapTrader
DefaultDirName={localappdata}\Programs\CheapTrader
DefaultGroupName=CheapTrader
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist-release
OutputBaseFilename=CheapTrader-{#AppVersion}-setup
SetupIconFile=..\backend\build\cheaptrader.ico
UninstallDisplayIcon={app}\CheapTrader.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=CheapTrader

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist-release\CheapTrader.exe"; DestDir: "{app}"; Flags: ignoreversion
; the settings start safe (MetaTrader if there is one, no orders); a file that is there already is the user's
Source: "..\dist-release\.env"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CheapTrader"; Filename: "{app}\CheapTrader.exe"
Name: "{autodesktop}\CheapTrader"; Filename: "{app}\CheapTrader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CheapTrader.exe"; Description: "{cm:LaunchProgram,CheapTrader}"; Flags: nowait postinstall skipifsilent
