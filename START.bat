@echo off
cd /d "%~dp0"
echo.
echo ==========================================
echo            PRIME MVP v1.3
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 goto PY

where python >nul 2>nul
if %errorlevel%==0 goto PYTHON

echo Python is not installed.
pause
exit /b

:PY
for /f "tokens=5" %%P in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do taskkill /F /PID %%P >nul 2>&1
start "" cmd /k "cd /d ""%~dp0"" && py server.py"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765
exit /b

:PYTHON
for /f "tokens=5" %%P in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do taskkill /F /PID %%P >nul 2>&1
start "" cmd /k "cd /d ""%~dp0"" && python server.py"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765
exit /b
