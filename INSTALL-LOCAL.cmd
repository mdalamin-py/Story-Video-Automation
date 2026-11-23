@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installed. FFmpeg and FFprobe must be on PATH or keep the existing tested runtime.
echo Double-click VIDEO-MAKER.cmd to open the prompt box.
pause
exit /b 0
:failed
echo Setup failed. Read the error above.
pause
exit /b 1
