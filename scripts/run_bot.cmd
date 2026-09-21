@echo off
rem Start the Technical Commons bot.
rem Used by the Windows scheduled task ("At log on") and for manual runs.
rem Console output is appended to logs\bot-console.log (gitignored); the bot also
rem writes its own log under RUNTIME_DIR\logs.

cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" -m commons.discord.bot >> "logs\bot-console.log" 2>&1
