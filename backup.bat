@echo off
cd /d "%~dp0"

set PYTHON_CMD=
python --version >nul 2>&1 && set PYTHON_CMD=python
if not defined PYTHON_CMD (
    py -3 --version >nul 2>&1 && set PYTHON_CMD=py -3
)
if not defined PYTHON_CMD (
    echo [ERROR] Python not found.
    goto :end
)

%PYTHON_CMD% backup.py

:end
pause
