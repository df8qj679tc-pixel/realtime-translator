@echo off
setlocal
cd /d "%~dp0"
python realtime_translator.py
if errorlevel 1 (
  echo.
  echo Failed to start. Please make sure Python is installed and available in PATH.
  pause
)
