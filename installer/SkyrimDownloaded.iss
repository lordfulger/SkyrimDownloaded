; SkyrimDownloaded installer (Inno Setup 6). Built by the GitHub workflow:
;   ISCC /DAppVersion=1.2.3 installer\SkyrimDownloaded.iss
; It packs the folder build of the app (dist\app\SkyrimDownloaded) into dist\SkyrimDownloaded-Setup.exe.
;
; By default it installs for the current user only (in %LOCALAPPDATA%\Programs), so no admin
; rights are needed and updates can install themselves. Settings, lists and the login live in
; %APPDATA%\SkyrimDownloaded and stay when updating or uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7E-4D2C-9A1F-5E4B3C2D1A0F}
AppName=SkyrimDownloaded
AppVersion={#AppVersion}
AppVerName=SkyrimDownloaded {#AppVersion}
AppPublisher=lordfulger
AppPublisherURL=https://github.com/lordfulger/SkyrimDownloaded
AppSupportURL=https://github.com/lordfulger/SkyrimDownloaded/issues
AppUpdatesURL=https://github.com/lordfulger/SkyrimDownloaded/releases
DefaultDirName={autopf}\SkyrimDownloaded
DefaultGroupName=SkyrimDownloaded
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=SkyrimDownloaded-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\SkyrimDownloaded.exe
UninstallDisplayName=SkyrimDownloaded
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; files of the previous version that this one may no longer have
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\app\SkyrimDownloaded\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SkyrimDownloaded"; Filename: "{app}\SkyrimDownloaded.exe"
Name: "{autodesktop}\SkyrimDownloaded"; Filename: "{app}\SkyrimDownloaded.exe"; Tasks: desktopicon

[Run]
; After a normal install: offer to open the app. (A silent update is reopened by the app's updater.)
Filename: "{app}\SkyrimDownloaded.exe"; Description: "{cm:LaunchProgram,SkyrimDownloaded}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
