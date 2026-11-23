@echo off
setlocal
cd /d "%~dp0"
node studio.mjs
if errorlevel 1 pause
