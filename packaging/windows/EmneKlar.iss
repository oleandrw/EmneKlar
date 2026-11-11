; EmneKlar – installasjonsprogram for Windows (Inno Setup 6). Bygges av scripts/build_installer.py:
;
;   ISCC /DAppVersion=0.2.0 /DNumericVersion=0.2.0.0 /DSourceDir=<utpakket installasjon> /DOutputDir=<målmappe>
;        [/DTestBuild] [/DSignToolName=<navn> /S<navn>=<kommando>] EmneKlar.iss
;
; SourceDir er installasjonen slik den skal ligge på maskinen: programpakken (EmneKlar-<versjon>.zip) pakket ut, med
; kjøretiden (EmneKlar-runtime-win-amd64-<id>.zip) i undermappen runtime. Installasjonsprogrammet kopierer den,
; lager snarveier og kontrollerer at EmneKlar kan lastes. Det laster ikke ned noe og installerer ikke Python.
;
; * Per bruker (ingen administratorrettigheter), fast mappe: %LOCALAPPDATA%\Programs\EmneKlar. Oppdateringen
;   (update.bat) skriver i den mappen, og brukerens data ligger i %LOCALAPPDATA%\EmneKlar – de røres ikke her.
; * TestBuild gir en egen installasjon («EmneKlar (test)», egen mappe, egen AppId), slik at installasjon og
;   avinstallering kan prøves uten å berøre en vanlig installasjon. Testutgaven får også sin egen datamappe, port
;   og tjeneste i Legitimasjonsbehandling: installasjonsprogrammet skriver emneklar.local.json i programmappen (se
;   backend/emneklar/config.py), så den aldri åpner, kopierer eller endrer brukerens vanlige data – og aldri
;   erstatter det ekte Canvas-tokenet – uansett om den startes fra snarveien, start.bat eller update.bat.

#ifndef AppVersion
  #error AppVersion mangler. Bruk scripts/build_installer.py.
#endif
#ifndef NumericVersion
  #error NumericVersion mangler. Bruk scripts/build_installer.py.
#endif
#ifndef SourceDir
  #error SourceDir mangler. Bruk scripts/build_installer.py.
#endif
#ifndef OutputDir
  #error OutputDir mangler. Bruk scripts/build_installer.py.
#endif

#ifdef TestBuild
  #define AppName "EmneKlar (test)"
  #define AppIdValue "{{2C012464-A983-487C-B3EF-C3904838110F}"
  #define DirName "EmneKlar-test"
  #define OutputName "EmneKlar-" + AppVersion + "-setup-test"
  #define DataDir "{localappdata}\EmneKlar-test-data"
  #define LocalPort "8791"
  #define LocalKeyring "EmneKlar-test"
#else
  #define AppName "EmneKlar"
  #define AppIdValue "{{077D937C-0194-43D0-B8E5-D4F21205B360}"
  #define DirName "EmneKlar"
  #define OutputName "EmneKlar-" + AppVersion + "-setup"
  #define DataDir "{localappdata}\EmneKlar"
#endif
#ifdef LocalKeyring
  #define KeyringShown LocalKeyring
#else
  #define KeyringShown "EmneKlar"
#endif

[Setup]
AppId={#AppIdValue}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=EmneKlar
AppPublisherURL=https://github.com/oleandrw/EmneKlar
AppSupportURL=https://github.com/oleandrw/EmneKlar/issues
AppUpdatesURL=https://github.com/oleandrw/EmneKlar/releases
VersionInfoVersion={#NumericVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoDescription={#AppName} – installasjonsprogram
DefaultDirName={localappdata}\Programs\{#DirName}
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile=EmneKlar.ico
UninstallDisplayIcon={app}\EmneKlar.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
; EmneKlar is stopped with its own stop command (see [Code]); the Restart Manager is not needed.
CloseApplications=no
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Languages]
Name: "nb"; MessagesFile: "compiler:Languages\Norwegian.isl"

[Tasks]
Name: "desktopicon"; Description: "Lag snarvei på skrivebordet"; GroupDescription: "Snarveier:"

[InstallDelete]
; The result must be exactly this version: files of another version (program code that is found by name, database
; migrations, the previous runtime) are removed before the new ones are copied. User data is not in this folder.
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\.update"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "EmneKlar.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; pythonw.exe: no console window. The browser is EmneKlar's user interface.
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-m emneklar"; WorkingDir: "{app}"; IconFilename: "{app}\EmneKlar.ico"; Comment: "Start EmneKlar. Nettleseren åpnes automatisk."
Name: "{group}\Avslutt {#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-m emneklar.manage stop"; WorkingDir: "{app}"; IconFilename: "{app}\EmneKlar.ico"; Comment: "Stopp EmneKlar på denne maskinen."
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-m emneklar"; WorkingDir: "{app}"; IconFilename: "{app}\EmneKlar.ico"; Comment: "Start EmneKlar. Nettleseren åpnes automatisk."; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: "-m emneklar"; WorkingDir: "{app}"; Description: "Start {#AppName} nå"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Everything EmneKlar and its updates have written in the program folder (compiled files, update backups, files of
; newer versions). The user's data in %LOCALAPPDATA%\EmneKlar is not here and is never removed.
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\.update"
Type: files; Name: "{app}\*.bat"
Type: files; Name: "{app}\*.md"
Type: files; Name: "{app}\VERSION"
Type: files; Name: "{app}\install.json"
Type: files; Name: "{app}\emneklar.local.json"
Type: files; Name: "{app}\EmneKlar.ico"
Type: dirifempty; Name: "{app}"

[Code]
const
  NewVersion = '{#AppVersion}';

function RuntimeFile(const Name: String): String;
begin
  Result := ExpandConstant('{app}\runtime\') + Name;
end;

{ True when another process has the file open (a running EmneKlar keeps its interpreter open). }
function FileInUse(const FileName: String): Boolean;
var
  Stream: TFileStream;
begin
  Result := False;
  if not FileExists(FileName) then
    Exit;
  try
    Stream := TFileStream.Create(FileName, fmOpenReadWrite or fmShareExclusive);
    Stream.Free;
  except
    Result := True;
  end;
end;

function EmneKlarRunning(): Boolean;
begin
  Result := FileInUse(RuntimeFile('pythonw.exe')) or FileInUse(RuntimeFile('python.exe'));
end;

{ Stops a running EmneKlar with its own stop command, then waits until its files are free.
  True when nothing is running any more. }
function StopEmneKlar(): Boolean;
var
  ResultCode, Attempt: Integer;
begin
  if FileExists(RuntimeFile('python.exe')) then
    Exec(RuntimeFile('python.exe'), '-m emneklar.manage stop --timeout 30', ExpandConstant('{app}'), SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
  for Attempt := 1 to 20 do
  begin
    if not EmneKlarRunning() then
      Break;
    Sleep(500);
  end;
  Result := not EmneKlarRunning();
end;

{ The number before the next '.', '-' or '+' in S; S is shortened to what follows the separator. }
function NextNumber(var S: String): Integer;
var
  I: Integer;
  Digits: String;
begin
  Digits := '';
  I := 1;
  while (I <= Length(S)) and (S[I] >= '0') and (S[I] <= '9') do
  begin
    Digits := Digits + S[I];
    I := I + 1;
  end;
  if (I <= Length(S)) and (S[I] = '.') then
    S := Copy(S, I + 1, Length(S))
  else
    S := '';
  Result := StrToIntDef(Digits, 0);
end;

{ Compares MAJOR.MINOR.PATCH (what follows, e.g. -rc.1, is ignored): negative, zero or positive. }
function CompareVersions(A, B: String): Integer;
var
  Part: Integer;
begin
  Result := 0;
  for Part := 1 to 3 do
  begin
    Result := NextNumber(A) - NextNumber(B);
    if Result <> 0 then
      Exit;
  end;
end;

function InstalledVersion(): String;
var
  Content: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(ExpandConstant('{app}\VERSION'), Content) then
    Result := Trim(String(Content));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Installed: String;
begin
  Result := '';
  Installed := InstalledVersion();
  if (Installed <> '') and (CompareVersions(Installed, NewVersion) > 0) then
  begin
    Result := 'En nyere versjon av EmneKlar (' + Installed + ') er allerede installert. Dette installasjonsprogrammet '
      + 'inneholder versjon ' + NewVersion + ' og kan ikke erstatte en nyere versjon, fordi databasen kan være '
      + 'oppdatert. Last ned det nyeste installasjonsprogrammet fra GitHub.';
    Exit;
  end;
  if not StopEmneKlar() then
    Result := 'EmneKlar kjører og lot seg ikke avslutte. Velg «Avslutt EmneKlar» i programmet eller i Start-menyen, '
      + 'og kjør installasjonsprogrammet på nytt.';
end;

#ifdef LocalPort
{ The test build only: its own data folder, port and credential-store service, as defaults of this installation
  (emneklar.local.json). Written as UTF-8, with the backslashes of the path doubled as JSON wants them. }
procedure WriteLocalDefaults();
var
  DataFolder: String;
  Lines: TArrayOfString;
begin
  DataFolder := ExpandConstant('{#DataDir}');
  StringChangeEx(DataFolder, '\', '\\', True);
  SetArrayLength(Lines, 1);
  Lines[0] := '{"data_dir": "' + DataFolder + '", "port": {#LocalPort}, "keyring_service": "{#LocalKeyring}"}';
  if not SaveStringsToUTF8File(ExpandConstant('{app}\emneklar.local.json'), Lines, False) then
    RaiseException('Kunne ikke skrive emneklar.local.json. Testutgaven er ikke trygg å starte uten den.');
end;
#endif

{ After the files are in place: the same check as setup.bat – that EmneKlar can be loaded with the bundled runtime.
  Nothing is downloaded or installed. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;
#ifdef LocalPort
  WriteLocalDefaults();
#endif
  WizardForm.StatusLabel.Caption := 'Kontrollerer installasjonen …';
  if not Exec(RuntimeFile('python.exe'), '"' + ExpandConstant('{app}\scripts\setup.py') + '" --no-pause',
              ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    ResultCode := -1;
  Log('Kontroll av installasjonen (scripts\setup.py): kode ' + IntToStr(ResultCode));
  if ResultCode <> 0 then
    SuppressibleMsgBox('EmneKlar ble installert, men kontrollen av installasjonen feilet (kode '
      + IntToStr(ResultCode) + '). Start EmneKlar og se om programmet åpnes. Hvis ikke, står detaljene i '
      + ExpandConstant('{#DataDir}\logs\setup.log') + '.', mbError, MB_OK, IDOK);
end;

function InitializeUninstall(): Boolean;
begin
  Result := StopEmneKlar();
  if not Result then
    SuppressibleMsgBox('EmneKlar kjører og lot seg ikke avslutte. Velg «Avslutt EmneKlar» i programmet eller i '
      + 'Start-menyen, og prøv å avinstallere på nytt.', mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    SuppressibleMsgBox('EmneKlar er avinstallert. Dataene dine (database, sikkerhetskopier, rapporter og logger) '
      + 'ligger fortsatt i ' + ExpandConstant('{#DataDir}') + '. Slett mappen selv hvis du vil '
      + 'fjerne dem. Canvas-token og KI-nøkler fjerner du i Windows Legitimasjonsbehandling (oppføringene med '
      + '«{#KeyringShown}»).', mbInformation, MB_OK, IDOK);
end;
