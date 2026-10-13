@echo off
cd /d "%~dp0"
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Kurulum.ps1"
if errorlevel 1 pause
