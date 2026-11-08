; Inno Setup script for Boxset.  Build after PyInstaller:  ISCC packaging\installer.iss
#define AppName "Boxset"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8F50A10C-A9A2-4424-B009-9F5C86D8EE91}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=RamenNuudls
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\Boxset.exe
OutputDir=..\dist
OutputBaseFilename=BoxsetSetup-{#AppVersion}
SetupIconFile=boxset.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
ChangesAssociations=yes
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Boxset\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Boxset.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Boxset.exe"; Tasks: desktopicon

[Registry]
; .boxset projects and .boxtheme theme packs open in Boxset
Root: HKA; Subkey: "Software\Classes\.boxset"; ValueType: string; ValueData: "Boxset.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Boxset.Project"; ValueType: string; ValueData: "Boxset project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Boxset.Project\DefaultIcon"; ValueType: string; ValueData: "{app}\Boxset.exe,0"
Root: HKA; Subkey: "Software\Classes\Boxset.Project\shell\open\command"; ValueType: string; ValueData: """{app}\Boxset.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.boxtheme"; ValueType: string; ValueData: "Boxset.Theme"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Boxset.Theme"; ValueType: string; ValueData: "Boxset theme pack"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Boxset.Theme\DefaultIcon"; ValueType: string; ValueData: "{app}\Boxset.exe,0"
Root: HKA; Subkey: "Software\Classes\Boxset.Theme\shell\open\command"; ValueType: string; ValueData: """{app}\Boxset.exe"" ""%1"""

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2…"; Check: NeedsWebView2; Flags: waituntilterminated skipifdoesntexist
Filename: "{app}\Boxset.exe"; Description: "Open Boxset"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsWebView2: Boolean;
var v: String;
begin
  Result := not (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0'))
        and not (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0'));
end;
