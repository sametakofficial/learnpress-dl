@echo off
setlocal
set SCRIPT_DIR=%~dp0

if "%~1"=="" (
  echo Usage: run.bat ^<cookie-file^> [output-dir]
  exit /b 1
)

set COOKIE_FILE=%~1
set OUTPUT_DIR=%~2
if "%OUTPUT_DIR%"=="" set OUTPUT_DIR=%SCRIPT_DIR%output

"%SCRIPT_DIR%learnpress-dl.exe" --cookie-file "%COOKIE_FILE%" --output-dir "%OUTPUT_DIR%" --download-videos --download-transcripts --zip-courses --verbose

endlocal
