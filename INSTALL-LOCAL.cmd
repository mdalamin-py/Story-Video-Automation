@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
where ffmpeg >nul 2>nul
if errorlevel 1 if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
  echo FFmpeg was not found. Install it with:  winget install Gyan.FFmpeg
  echo or unzip an FFmpeg build into tools\ffmpeg, or set FFMPEG_PATH in .env.
)
echo Installed.
echo Double-click VIDEO-MAKER.cmd to open the prompt box.
pause
exit /b 0
:failed
echo Setup failed. Read the error above.
pause
exit /b 1
