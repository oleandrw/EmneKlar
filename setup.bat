@echo off
rem EmneKlar - setup. Double-click once after downloading EmneKlar; safe to run again (it repairs the
rem installation). No administrator rights are needed. See scripts\setup.py for the details.
rem Arguments: --no-pause (do not wait for a key press at the end), --strict (tested versions only).
rem Optional: set EMNEKLAR_PYTHON to the full path of a python.exe to use that interpreter.
rem Keep everything above "chcp 65001" ASCII-only: cmd.exe reads those lines with the OEM code page.
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title EmneKlar – oppsett
cd /d "%~dp0"

rem Find Python 3.11 or newer: EMNEKLAR_PYTHON, then the Python launcher (py -3), then python on PATH.
set "EMNEKLAR_SETUP_PY="
set "EMNEKLAR_OLD_PY="
if defined EMNEKLAR_PYTHON call :probe "%EMNEKLAR_PYTHON%"
if not defined EMNEKLAR_SETUP_PY call :probe py -3
if not defined EMNEKLAR_SETUP_PY call :probe python
if not defined EMNEKLAR_SETUP_PY goto :no_python

rem CALL also works when the interpreter is a .bat shim (e.g. pyenv-win) instead of an .exe.
call %EMNEKLAR_SETUP_PY% "%~dp0scripts\setup.py" %*
set "EMNEKLAR_EXIT=%ERRORLEVEL%"
call :maybe_pause %*
exit /b %EMNEKLAR_EXIT%

:probe
rem Usable if it starts and is Python 3.11 or newer. An older one is remembered for the message below.
call %* -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 3)" >nul 2>&1
if "%ERRORLEVEL%"=="0" set "EMNEKLAR_SETUP_PY=%*"
if "%ERRORLEVEL%"=="3" if not defined EMNEKLAR_OLD_PY set "EMNEKLAR_OLD_PY=%*"
exit /b 0

:no_python
echo.
if defined EMNEKLAR_OLD_PY goto :python_too_old
echo Fant ikke Python på denne maskinen. EmneKlar trenger Python 3.11 eller nyere.
goto :python_help

:python_too_old
echo Fant Python, men versjonen er for gammel:
call %EMNEKLAR_OLD_PY% --version
echo EmneKlar trenger Python 3.11 eller nyere.

:python_help
echo.
echo Slik installerer du Python (det trengs ikke administratorrettigheter):
echo   1. Åpne https://www.python.org/downloads/windows/ og last ned Python 3.14 eller 3.13.
echo   2. Kjør installasjonsprogrammet og følg instruksjonene.
echo   3. Kjør setup.bat på nytt.
call :maybe_pause %*
exit /b 1

:maybe_pause
for %%A in (%*) do if /i "%%~A"=="--no-pause" exit /b 0
echo.
pause
exit /b 0
