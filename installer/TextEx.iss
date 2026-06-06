; =============================================================================
; TextEx.iss — Inno Setup 6 Installer Script
;
; Compile with:
;   build_installer.bat
; Or manually:
;   "C:\Program Files (x86)\Inno Setup 6\iscc.exe" installer\TextEx.iss
;
; Requirements:
;   - Inno Setup 6 installed
;   - dist\TextEx\ must exist (run build.bat first)
;
; Output: installer\TextEx-Setup-1.0.0.exe
; =============================================================================

#define AppName        "TextEx"
#define AppVersion     "1.0.0"
#define AppPublisher   "TextEx"
#define AppURL         "https://github.com/Piyush-Gupta04/TextEx"
#define AppExeName     "TextEx.exe"
#define AppDescription "Smart Text Extractor — Screen OCR & Translation"

[Setup]
; ── Identity ────────────────────────────────────────────────────────────────
AppId={{A7B3C4D5-E6F7-4890-ABCD-1234567890AB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppDescription}
VersionInfoCompany={#AppPublisher}

; ── Install location ────────────────────────────────────────────────────────
; {autopf} = C:\Program Files or C:\Program Files (x86) depending on arch
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=no

; ── Installer output ────────────────────────────────────────────────────────
; Run script from project root (one level above installer/)
OutputDir=..\installer
OutputBaseFilename=TextEx-Setup-{#AppVersion}

; ── Compression ─────────────────────────────────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ── Architecture ─────────────────────────────────────────────────────────────
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ── UAC / privileges ─────────────────────────────────────────────────────────
; PrivilegesRequired=admin ensures shortcuts go to All Users.
; Set to lowest for per-user installs (no UAC prompt) if preferred.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; ── Icon ─────────────────────────────────────────────────────────────────────
SetupIconFile=..\assets\textex.ico
UninstallDisplayIcon={app}\{#AppExeName}
WizardSmallImageFile=compiler:WizModernSmallImage.bmp

; ── Misc ─────────────────────────────────────────────────────────────────────
DisableProgramGroupPage=no
DisableWelcomePage=no
ShowLanguageDialog=no
ChangesAssociations=no
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";   Description: "{cm:CreateDesktopIcon}";   GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startmenuicon"; Description: "Create Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; ── Main application bundle (from PyInstaller one-folder output) ─────────────
; Source path is relative to the .iss file location (installer/)
Source: "..\dist\TextEx\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; ── Start Menu ───────────────────────────────────────────────────────────────
Name: "{group}\{#AppName}";                          Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}";               Filename: "{uninstallexe}"

; ── Desktop ──────────────────────────────────────────────────────────────────
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; ── Launch after install (optional checkbox) ─────────────────────────────────
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; ── Remove PyInstaller temp files left by the app ────────────────────────────
Type: filesandordirs; Name: "{app}\_MEI*"

[Code]
// ─────────────────────────────────────────────────────────────────────────────
// Custom installer page: inform the user where their data lives
// so they know it is safe across upgrades.
// ─────────────────────────────────────────────────────────────────────────────

function GetDataDir(): String;
begin
  Result := ExpandConstant('{userappdata}\TextEx');
end;

procedure InitializeWizard;
var
  InfoPage: TWizardPage;
  InfoLabel: TNewStaticText;
  DataDir: String;
begin
  DataDir := GetDataDir();
  InfoPage := CreateCustomPage(
    wpSelectDir,
    'User Data Location',
    'Your OCR history, screenshots, and settings are stored separately from the application.'
  );

  InfoLabel := TNewStaticText.Create(InfoPage);
  InfoLabel.Parent := InfoPage.Surface;
  InfoLabel.Left   := 0;
  InfoLabel.Top    := 0;
  InfoLabel.Width  := InfoPage.SurfaceWidth;
  InfoLabel.AutoSize := False;
  InfoLabel.WordWrap := True;
  InfoLabel.Height := 200;
  InfoLabel.Caption :=
    'TextEx stores your personal data in:' + #13#10 +
    #13#10 +
    '  ' + DataDir + #13#10 +
    #13#10 +
    'This directory contains:' + #13#10 +
    '  • history.db   — OCR extraction history' + #13#10 +
    '  • captures\    — Screenshot images' + #13#10 +
    '  • logs\        — Application log files' + #13#10 +
    #13#10 +
    'Settings are stored in the Windows registry under:' + #13#10 +
    '  HKCU\Software\TextEx\SmartTextExtractor' + #13#10 +
    #13#10 +
    'Your data will NOT be deleted when you upgrade or uninstall TextEx.' + #13#10 +
    'To remove all data, delete the folder above manually.' + #13#10 +
    #13#10 +
    'First Launch Note: OCR models are downloaded on first use (~500 MB).' + #13#10 +
    'An internet connection is required the first time you run a capture.';
end;
