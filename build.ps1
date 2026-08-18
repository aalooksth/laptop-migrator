Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Building Standalone LaptopMigrator.exe with PyInstaller" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

Write-Host "`n[1/3] Installing / Verifying build dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install pyinstaller -r requirements.txt

Write-Host "`n[2/3] Compiling standalone executable..." -ForegroundColor Yellow
pyinstaller --noconfirm --onefile `
    --name "LaptopMigrator" `
    --icon "favicon.ico" `
    --add-data "favicon.ico;." `
    --collect-all "uvicorn" `
    --collect-all "fastapi" `
    --collect-all "pydantic" `
    --collect-all "starlette" `
    --hidden-import "uvicorn.logging" `
    --hidden-import "uvicorn.loops" `
    --hidden-import "uvicorn.loops.auto" `
    --hidden-import "uvicorn.protocols" `
    --hidden-import "uvicorn.protocols.http" `
    --hidden-import "uvicorn.protocols.http.auto" `
    --hidden-import "uvicorn.protocols.websockets" `
    --hidden-import "uvicorn.protocols.websockets.auto" `
    --hidden-import "uvicorn.lifespan" `
    --hidden-import "uvicorn.lifespan.on" `
    app.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[3/3] Build complete! Executable is located at:" -ForegroundColor Green
    Write-Host "  -> dist\LaptopMigrator.exe`n" -ForegroundColor Green
} else {
    Write-Host "`n[ERROR] Build failed. Review the console logs above.`n" -ForegroundColor Red
}
