@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
set "PY=%QFNU_PYTHON%"
if not defined PY set "PY=python"
set QFNU_PROFILE=qzm
:loop
"%PY%" -m qfnu_lib.cli daily >> "%~dp0logs\task-qzm.log" 2>&1
echo [%date% %time%] daemon exited, restarting in 30s >> "%~dp0logs\task-qzm.log"
timeout /t 30 /nobreak >nul
goto loop