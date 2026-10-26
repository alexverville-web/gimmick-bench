@echo off
rem Double-click to open the Gimmick Bench launcher (Windows).
cd /d "%~dp0\.."
set PY=
if exist runtime\python\python.exe set PY=runtime\python\python.exe
if not defined PY where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Gimmick Bench needs Python 3.9 or newer. Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)
%PY% -m gimmick_bench ui
pause
