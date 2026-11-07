@echo off
setlocal
set "PYTHONUTF8=1"
set "SKILL=%~dp0"
set "RUNTIME=%LOCALAPPDATA%\lan-file-share-assistant"
if not defined LOCALAPPDATA goto missing
if exist "%SKILL%.venv\Scripts\python.exe" goto venv
where py.exe >nul 2>nul
if errorlevel 1 goto systempython
py -3 "%SKILL%scripts\lan_share.py" quick-folder --work-dir "%RUNTIME%" --host-kind local --host-evidence user_confirmed --open-local
 goto done
:systempython
where python.exe >nul 2>nul
if errorlevel 1 goto missing
python "%SKILL%scripts\lan_share.py" quick-folder --work-dir "%RUNTIME%" --host-kind local --host-evidence user_confirmed --open-local
 goto done
:venv
"%SKILL%.venv\Scripts\python.exe" "%SKILL%scripts\lan_share.py" quick-folder --work-dir "%RUNTIME%" --host-kind local --host-evidence user_confirmed --open-local
 goto done
:missing
echo Set up Python 3.9 or newer and the Skill dependencies first. See references\runtime.md.
:done
pause
