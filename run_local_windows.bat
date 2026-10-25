@echo off
chcp 65001 >nul
title Medal PACS Telegram Bot (Local Iran Direct Mode v13.2)
echo ============================================================
echo   Medal PACS Telegram Bot v13.2 - Direct Iran Network Mode
echo ============================================================
echo.
if "%BOT_TOKEN%"=="" (
    set /p BOT_TOKEN="Lotfan BOT_TOKEN telegram khod ra vared konid: "
)
echo.
echo [1/2] Installing Python requirements...
pip install -r requirements.txt
echo.
echo [2/2] Starting Bot directly on your Iran internet (No Proxy Needed)...
python bot.py
pause
