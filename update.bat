@echo off
rem EmneKlar - update. Double-click to update EmneKlar to the newest version (see scripts\update.py).
rem EmneKlar itself starts this file with --from-app [--allow-major] (Innstillinger in the app).
rem Other arguments: --allow-major, --no-start, --no-pause. Exit codes: 0 ok, 1 failed (rolled back), 2 not started.
rem Keep everything above "chcp 65001" ASCII-only: cmd.exe reads those lines with the OEM code page.
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title EmneKlar – oppdatering

set "EMNEKLAR_PY=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%EMNEKLAR_PY%" goto :not_installed
if not exist "%~dp0scripts\update.py" goto :incomplete

rem Run a copy of update.py from %TEMP%: the update may replace everything in this folder.
set "EMNEKLAR_UPDATE_TMP=%TEMP%\EmneKlar-oppdatering-%RANDOM%%RANDOM%"
mkdir "%EMNEKLAR_UPDATE_TMP%" >nul 2>&1
copy /y "%~dp0scripts\update.py" "%EMNEKLAR_UPDATE_TMP%\update.py" >nul 2>&1 || goto :copy_failed

rem cmd.exe keeps reading this file while it runs, and the update may replace it. Everything from here on
rem is therefore on ONE line, which cmd.exe has read completely before Python starts.
"%EMNEKLAR_PY%" "%EMNEKLAR_UPDATE_TMP%\update.py" --repo "%~dp0." --temp-copy %* & call exit /b %%ERRORLEVEL%%

:not_installed
echo.
echo EmneKlar er ikke installert i denne mappen ennå (fant ikke backend\.venv).
echo Kjør setup.bat først. Da installeres den versjonen som ligger i denne mappen.
call :maybe_pause %*
exit /b 2

:incomplete
echo.
echo Mappen ser ufullstendig ut: scripts\update.py mangler.
echo Last ned EmneKlar på nytt, eller kjør setup.bat for å reparere installasjonen.
call :maybe_pause %*
exit /b 2

:copy_failed
echo.
echo Klarte ikke å kopiere oppdateringsprogrammet til den midlertidige mappen:
echo "%EMNEKLAR_UPDATE_TMP%"
echo Ingenting er endret. Sjekk at det er ledig diskplass, og prøv igjen.
call :maybe_pause %*
exit /b 1

:maybe_pause
for %%A in (%*) do if /i "%%~A"=="--no-pause" exit /b 0
echo.
pause
exit /b 0
