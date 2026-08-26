@echo off
REM Starts RevPulse: API on 8000, dashboard on 5173.
REM Two windows open and stay open. Close them to stop the app.

echo Starting RevPulse...

start "RevPulse API" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --port 8000"
timeout /t 6 /nobreak >nul
start "RevPulse Dashboard" cmd /k "cd /d %~dp0frontend && npm run dev -- --port 5173 --strictPort"
timeout /t 5 /nobreak >nul

echo.
echo   Dashboard : http://localhost:5173
echo   API       : http://127.0.0.1:8000/docs
echo.
echo Leave both windows open while you use the app.
start http://localhost:5173
