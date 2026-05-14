#define MyAppName "Pokemon Save Editor"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Community Tools"
#define MyAppExeName "PokemonIndigoSaveEditor.exe"

[Setup]
AppId={{8CC3F304-57F4-4E22-9E74-73E9DAA5F640}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Pokemon Save Editor
DisableProgramGroupPage=yes
LicenseFile=
SetupIconFile=..\assets\masterball.ico
UninstallDisplayIcon={app}\PokemonIndigoSaveEditor.exe
OutputDir=dist
OutputBaseFilename=PokemonSaveEditor_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\PokemonIndigoSaveEditor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\launch_save_editor_gui.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Pokemon Save Editor"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Pokemon Save Editor"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--probe --game-root ""{code:GetGameRoot}"" --save ""{code:GetSavePath}"""; Description: "Run first-time mapping"; Flags: postinstall waituntilterminated skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--game-root ""{code:GetGameRoot}"" --save ""{code:GetSavePath}"""; Description: "Launch Pokemon Save Editor"; Flags: postinstall nowait skipifsilent

[Code]
var
  GameRootPage: TInputDirWizardPage;
  SavePage: TInputFileWizardPage;

function GetGameRoot(Param: string): string;
begin
  Result := Trim(GameRootPage.Values[0]);
end;

function GetSavePath(Param: string): string;
begin
  Result := Trim(SavePage.Values[0]);
end;

procedure InitializeWizard;
begin
  GameRootPage := CreateInputDirPage(
    wpSelectDir,
    'Select Game Root',
    'Choose the game root folder',
    'The game root must contain a "Data" folder. "PBS" is optional for some games.',
    False,
    ''
  );
  GameRootPage.Add('');
  GameRootPage.Values[0] := ExpandConstant('{src}');

  SavePage := CreateInputFilePage(
    GameRootPage.ID,
    'Select Save File',
    'Choose a save file for first-time mapping',
    'Select a .rxdata save file from the target game profile.'
  );
  SavePage.Add('Save file', 'RGSS Save (*.rxdata)|*.rxdata|All files (*.*)|*.*', '.rxdata');
end;

function IsValidGameRoot(const Root: string): Boolean;
begin
  Result :=
    DirExists(AddBackslash(Root) + 'Data') and
    (
      DirExists(AddBackslash(Root) + 'PBS') or
      FileExists(AddBackslash(Root) + 'Game.exe') or
      FileExists(AddBackslash(Root) + 'Game.ini') or
      FileExists(AddBackslash(Root) + 'mkxp.json') or
      (DirExists(AddBackslash(Root) + 'Graphics') and DirExists(AddBackslash(Root) + 'Audio'))
    );
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  rootPath: string;
  savePath: string;
begin
  Result := True;

  if CurPageID = GameRootPage.ID then
  begin
    rootPath := Trim(GameRootPage.Values[0]);
    if rootPath = '' then
    begin
      MsgBox('Please choose a game root folder.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not IsValidGameRoot(rootPath) then
    begin
      MsgBox(
        'Invalid game root folder.' + #13#10 +
        'Expected: Data folder (PBS optional for some games).',
        mbError,
        MB_OK
      );
      Result := False;
      Exit;
    end;
  end;

  if CurPageID = SavePage.ID then
  begin
    savePath := Trim(SavePage.Values[0]);
    if savePath = '' then
    begin
      MsgBox('Please choose a save file.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not FileExists(savePath) then
    begin
      MsgBox('Save file not found: ' + savePath, mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;
