@echo off
rem EmneKlar - start. Double-click to start EmneKlar; the browser opens automatically.
rem Arguments are passed on to EmneKlar, e.g. "start.bat --no-browser" or "start.bat --port 8800".
rem An installed EmneKlar is normally started from the Start menu (no console window). This file starts the same
rem program in a console window, where messages and the one-time login link are shown.
rem Keep everything above "chcp 65001" ASCII-only: cmd.exe reads those lines with the OEM code page.
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title EmneKlar

rem The installation's own Python runtime if it has one, else the environment made by setup.bat.
set "EMNEKLAR_PY=%~dp0backend\.venv\Scripts\python.exe"
if exist "%~dp0runtime\python.exe" set "EMNEKLAR_PY=%~dp0runtime\python.exe"
if not exist "%EMNEKLAR_PY%" goto :not_installed

cd /d "%~dp0backend"
"%EMNEKLAR_PY%" -m emneklar %*
set "EMNEKLAR_EXIT=%ERRORLEVEL%"
if "%EMNEKLAR_EXIT%"=="0" exit /b 0

set "EMNEKLAR_LOGS=%LOCALAPPDATA%\EmneKlar\logs"
if defined EMNEKLAR_DATA_DIR set "EMNEKLAR_LOGS=%EMNEKLAR_DATA_DIR%\logs"
echo.
echo EmneKlar stoppet på grunn av en feil (kode %EMNEKLAR_EXIT%). Se meldingene over.
echo Loggfiler: "%EMNEKLAR_LOGS%"
echo Hvis feilen ikke går over når du starter på nytt, kan du kjøre setup.bat for å kontrollere installasjonen.
echo.
pause
exit /b %EMNEKLAR_EXIT%

:not_installed
echo.
echo EmneKlar er ikke installert i denne mappen ennå (fant ikke backend\.venv).
echo Kjør setup.bat først (dobbeltklikk), og start deretter EmneKlar med start.bat.
echo.
pause
exit /b 1
