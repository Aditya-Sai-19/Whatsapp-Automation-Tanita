@echo off
title WhatsApp Automation Tool

REM Move to project folder
cd /d %~dp0

REM Install dependencies (only first time, later it skips fast)
py -m pip install -r requirements.txt

REM Run the main app
py app.py

pause