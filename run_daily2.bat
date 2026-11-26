@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
set "PY=%QFNU_PYTHON%"
if not defined PY set "PY=python"
set QFNU_PROFILE=qzm
"%PY%" -m qfnu_lib.cli daily >> "%~dp0logs\task-qzm.log" 2>&1