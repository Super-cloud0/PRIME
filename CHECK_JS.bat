@echo off
cd /d "%~dp0"
where node >nul 2>nul
if %errorlevel%==0 (
  echo Checking app.js syntax...
  node --check app.js
  if %errorlevel%==0 (
    echo.
    echo [OK] app.js syntax is valid.
  ) else (
    echo.
    echo [ERROR] app.js has a syntax error.
  )
) else (
  echo Node.js is not installed. Skip JS syntax check.
)
echo.
pause
