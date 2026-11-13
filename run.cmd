@echo off
setlocal
set "PROJECT=%~dp0"
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  py -3 "%PROJECT%src\main.py" %*
  exit /b
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" "%PROJECT%src\main.py" %*
  exit /b
)
python "%PROJECT%src\main.py" %*
