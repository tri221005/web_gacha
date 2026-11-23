@echo off
REM Chay web o che do production, san de Cloudflare Tunnel / VPS tro toi.
REM KHONG dung --reload: reload lap lai app moi thay doi, khong dung khi
REM website dang chay cho nguoi choi that.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if "%PORT%"=="" set PORT=8080
if "%HOST%"=="" set HOST=127.0.0.1
python -m uvicorn app.main:app --host %HOST% --port %PORT% --proxy-headers --forwarded-allow-ips="*"
