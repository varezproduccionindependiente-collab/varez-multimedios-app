[Setup]
AppName=Varez Servicios para Multimedios
AppVersion=1.0.0
DefaultDirName=D:\VarezMultimedios\app
DefaultGroupName=Varez Servicios para Multimedios
OutputDir=.
OutputBaseFilename=VarezMultimedios-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=
UninstallDisplayName=Varez Servicios para Multimedios
CreateUninstallRegKey=yes

[Files]
Source: "..\dist\VarezMultimedios\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Varez Servicios para Multimedios"; Filename: "{app}\VarezMultimedios.exe"
Name: "{autodesktop}\Varez Servicios para Multimedios"; Filename: "{app}\VarezMultimedios.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Run]
Filename: "{app}\VarezMultimedios.exe"; Description: "Abrir Varez Servicios para Multimedios"; Flags: nowait postinstall skipifsilent
