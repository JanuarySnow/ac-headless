@echo off
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m achl %*) else (python -m achl %*)
exit /b %errorlevel%
