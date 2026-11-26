@echo off
rem QFNU library auto check-in - run by Windows Task Scheduler
cd /d "%~dp0"
if not exist logs mkdir logs
set "PY=%QFNU_PYTHON%"
if not defined PY set "PY=python"
if not exist logs mkdir logs
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%PY%" -m qfnu_lib.cli run >> "logs\task.log" 2>&1