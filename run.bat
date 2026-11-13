@echo off
cd /d "%~dp0"
if exist "%~dp0TokenDuck.exe" (
    start "" "%~dp0TokenDuck.exe"
    exit /b
)
if exist "%~dp0dist\TokenDuck.exe" (
    start "" "%~dp0dist\TokenDuck.exe"
    exit /b
)
start "" pythonw.exe tokenduck.py
