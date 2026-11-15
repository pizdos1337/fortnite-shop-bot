@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist config.json (
  copy config.example.json config.json >nul
  echo Впиши токен бота в config.json и запусти снова.
  notepad config.json
  exit /b
)
python bot.py
pause
