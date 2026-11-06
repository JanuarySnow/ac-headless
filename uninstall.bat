@echo off
setlocal
if "%~1"=="" (
  echo usage: uninstall.bat "path\to\assettocorsa"
  exit /b 2
)
call "%~dp0run.bat" uninstall --ac "%~1"
exit /b %errorlevel%
