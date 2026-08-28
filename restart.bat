@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM Locate python via %USERPROFILE% to avoid hardcoding the Chinese username
set "PY=python"
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" if exist "C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"

REM Metadata online fill switch: 1=built-in crawler ON (P0 feature); 0=off.
REM Set to 0 if you do NOT want background network metadata fill on startup.
set "LIB_METADATA_ONLINE=1"

echo Using Python: %PY%
echo Stopping old service on port 8000 (if any)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /i ":8000" ^| findstr /i "LISTENING"') do (
    echo   killing PID %%a
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 >nul

REM Fix drive letter if the mobile HDD was plugged into another PC (e.g. F: -> G:)
echo Checking drive letter...
"%PY%" -c "import sqlite3,os;db=sqlite3.connect('data/library.db');rows=db.execute(\"SELECT id,file_path FROM books WHERE file_path LIKE '%%:%%' LIMIT 1\").fetchall();db.close();old=rows[0][1][:2] if rows else None;new=os.path.abspath('.').split(':')[0]+':';print('old',old,'new',new);exit(0 if old==new or not old else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo   drive letter changed, fixing...
    "%PY%" -c "import sqlite3,os;db=sqlite3.connect('data/library.db');books=db.execute(\"SELECT id,file_path FROM books WHERE file_path LIKE '%%:%%'\").fetchall();media=db.execute(\"SELECT id,file_path FROM media WHERE file_path LIKE '%%:%%'\").fetchall();new_drv=os.path.abspath('.').split(':')[0]+':';cnt=0;[(db.execute('UPDATE books SET file_path=? WHERE id=?',(new_drv+b[1][2:],b[0])),cnt:=cnt+1) for b in books if os.path.exists(new_drv+b[1][2:])];[(db.execute('UPDATE media SET file_path=? WHERE id=?',(new_drv+m[1][2:],m[0])),cnt:=cnt+1) for m in media if os.path.exists(new_drv+m[1][2:])];db.commit();print('fixed',cnt,'paths');db.close()"
) else (
    echo   drive letter OK
)

echo Starting Private_Lib.py (live logs below; window stays open while running)...
start "" http://localhost:8000
"%PY%" Private_Lib.py
if errorlevel 1 (
    echo.
    echo [START FAILED] See error above. Press any key to close.
    pause >nul
)
