@echo off
cd /d "%~dp0..\.."
call conda activate latextrans
if errorlevel 1 exit /b %errorlevel%
python -m main %*
exit /b %errorlevel%
