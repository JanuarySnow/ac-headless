@echo off
setlocal
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /O2 /W3 /LD achl.c /Fe:build\achl.dll /Fo:build\ d3d11.lib user32.lib
if errorlevel 1 exit /b 1
cl /nologo /O2 /W3 launch.c /Fe:build\achl_launch.exe /Fo:build\ /link /SUBSYSTEM:CONSOLE
if errorlevel 1 exit /b 1
echo built native\build\achl.dll and native\build\achl_launch.exe
