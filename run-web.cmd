@echo off
cd /d D:\web-gacha\web-gacha
call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
