@echo off
cd /d "%~dp0"
set "command=%~1"
if not defined command set "command=dev"

if /i "%command%"=="dev" goto dev
if /i "%command%"=="backend" goto backend
if /i "%command%"=="frontend" goto frontend
if /i "%command%"=="test" goto test

echo Usage: %~nx0 [dev^|backend^|frontend^|test]
exit /b 1

:dev
start "Project Chess backend" cmd.exe /c ".\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000"
cd frontend && call npm.cmd run dev -- --open
exit /b %errorlevel%

:backend
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
exit /b %errorlevel%

:frontend
cd frontend && call npm.cmd run dev
exit /b %errorlevel%

:test
.\.venv\Scripts\python.exe -m unittest backend.test_core
if errorlevel 1 exit /b %errorlevel%
cd frontend
if errorlevel 1 exit /b %errorlevel%
call npm.cmd run check
if errorlevel 1 exit /b %errorlevel%
call npm.cmd run build
exit /b %errorlevel%
