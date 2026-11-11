@echo off
rem EmneKlar - update. Double-click to update EmneKlar to the newest version (see scripts\update.py).
rem EmneKlar itself starts this file with --from-app [--allow-major] (Innstillinger in the app).
rem Other arguments: --allow-major, --no-start, --no-pause. Exit codes: 0 ok, 1 failed (rolled back), 2 not started.
rem Keep everything above "chcp 65001" ASCII-only: cmd.exe reads those lines with the OEM code page.
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title EmneKlar – oppdatering

if not exist "%~dp0scripts\update.py" goto :incomplete
set "EMNEKLAR_PY=%~dp0backend\.venv\Scripts\python.exe"
if exist "%~dp0runtime\python.exe" goto :bundled
if not exist "%EMNEKLAR_PY%" goto :not_installed
goto :run

:bundled
rem The installation has its own Python runtime (runtime\), and the update may replace that whole folder. The
rem update is therefore run by a copy of the interpreter (without the packages) in .update\python, so that
rem nothing in runtime\ is in use while it is replaced.
set "EMNEKLAR_PY=%~dp0.update\python\python.exe"
if exist "%~dp0.update\python" rmdir /s /q "%~dp0.update\python" >nul 2>&1
mkdir "%~dp0.update\python" >nul 2>&1
copy /y "%~dp0runtime\*.*" "%~dp0.update\python\" >nul 2>&1 || goto :runtime_copy_failed
if not exist "%EMNEKLAR_PY%" goto :runtime_copy_failed

:run
rem Run a copy of update.py from %TEMP%: the update may replace everything in this folder.
set "EMNEKLAR_UPDATE_TMP=%TEMP%\EmneKlar-oppdatering-%RANDOM%%RANDOM%"
mkdir "%EMNEKLAR_UPDATE_TMP%" >nul 2>&1
copy /y "%~dp0scripts\update.py" "%EMNEKLAR_UPDATE_TMP%\update.py" >nul 2>&1 || goto :copy_failed

rem cmd.exe keeps reading this file while it runs, and the update may replace it. Everything from here on
rem is therefore on ONE line, which cmd.exe has read completely before Python starts.
"%EMNEKLAR_PY%" "%EMNEKLAR_UPDATE_TMP%\update.py" --repo "%~dp0." --temp-copy %* & call exit /b %%ERRORLEVEL%%

:not_installed
echo.
echo EmneKlar er ikke installert i denne mappen ennå (fant verken runtime eller backend\.venv).
echo Kjør setup.bat først. Da installeres den versjonen som ligger i denne mappen.
call :maybe_pause %*
exit /b 2

:incomplete
echo.
echo Mappen ser ufullstendig ut: scripts\update.py mangler.
echo Installer EmneKlar på nytt. Dataene og innstillingene dine beholdes.
call :maybe_pause %*
exit /b 2

:runtime_copy_failed
echo.
echo Klarte ikke å klargjøre oppdateringen: den innebygde kjøretiden kunne ikke kopieres til
echo "%~dp0.update\python"
echo Ingenting er endret. Kjører en annen oppdatering allerede? Vent til den er ferdig, og prøv igjen.
call :maybe_pause %*
exit /b 1

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
