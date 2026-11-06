@echo off
setlocal
if "%~1"=="" (
  echo usage: install.bat "path\to\assettocorsa"
  exit /b 2
)
call "%~dp0run.bat" install --ac "%~1"
exit /b %errorlevel%
