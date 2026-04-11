@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Запуск через PowerShell: корректно передаются аргументы с пробелом в "User Data"
REM (через cmd "start" Chrome часто стартует БЕЗ remote debugging — порт 9222 молчит).

echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0chrome_start_debug.ps1"
if errorlevel 1 pause
