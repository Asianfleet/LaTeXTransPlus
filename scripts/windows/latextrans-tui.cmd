@echo off
cd /d "%~dp0..\.."
call conda activate latextrans
if errorlevel 1 exit /b %errorlevel%
python -c "from src.tui.app import run; run()" %*
exit /b %errorlevel%
