@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" launch.py hw_loop %*
pause
