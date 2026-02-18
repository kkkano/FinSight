@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_stage4_postgres_gate.ps1" %*
exit /b %errorlevel%

