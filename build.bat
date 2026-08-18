@echo off
echo =======================================================
echo   Building Standalone LaptopMigrator.exe with PyInstaller
echo =======================================================

echo [1/3] Installing / Verifying build dependencies...
python -m pip install --upgrade pip
python -m pip install pyinstaller -r requirements.txt

echo [2/3] Compiling standalone executable...
pyinstaller --noconfirm --onefile ^
    --name "LaptopMigrator" ^
    --icon "favicon.ico" ^
    --add-data "favicon.ico;." ^
    --collect-all "uvicorn" ^
    --collect-all "fastapi" ^
    --collect-all "pydantic" ^
    --collect-all "starlette" ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    app.py

echo [3/3] Build complete! Executable is located at:
echo   -^> dist\LaptopMigrator.exe
pause
