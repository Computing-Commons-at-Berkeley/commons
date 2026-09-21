@echo off
rem Double-click launcher for the bot (interactive).
rem Keeps the window open so errors are readable; Ctrl+C stops the bot.
rem For unattended startup use run_bot.cmd with Task Scheduler instead.

title Technical Commons Bot
cd /d "%~dp0.."

if not exist ".env" (
  echo ERROR: .env not found in %CD%
  echo Copy .env.example to .env and fill it in first.
  pause
  exit /b 1
)

echo Technical Commons bot
echo Working directory: %CD%
echo Log file:          runtime\logs\commons.log
echo Press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" -m commons.discord.bot

echo.
echo Bot exited with code %ERRORLEVEL%.
pause
