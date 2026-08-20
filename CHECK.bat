@echo off
cd /d "%~dp0"
echo Checking PRIME files...
for %%F in (index.html style.css app.js server.py requirements.txt) do (
  if exist "%%F" (echo [OK] %%F) else (echo [MISSING] %%F)
)
echo.
echo If START.bat is running, open:
echo http://127.0.0.1:8765
echo.
pause
