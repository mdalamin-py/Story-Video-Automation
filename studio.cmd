@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3, 12)" >nul 2>nul
if not errorlevel 1 (
  py -3 -m backend.launch
  exit /b
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" -m backend.launch
  exit /b
)
python -m backend.launch
