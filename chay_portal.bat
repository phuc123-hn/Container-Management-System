@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Dung Python co ultralytics (miniconda). Neu doi may, sua dong set PY cho dung duong dan.
set PY=C:\Users\VivoBook\miniconda3\python.exe
if not exist "%PY%" set PY=python
echo Dang dung Python: %PY%
"%PY%" python\portal_app.py
pause
