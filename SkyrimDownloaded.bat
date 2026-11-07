@echo off
rem Double-click to open SkyrimDownloaded. Pass arguments to use the command line,
rem e.g.  SkyrimDownloaded.bat run my-mods.txt --dry-run
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m skyrimdl %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or newer is needed: https://www.python.org/downloads/windows/
        pause
        exit /b 1
    )
    python -m skyrimdl %*
)
if errorlevel 1 pause
