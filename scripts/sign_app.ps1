# Automated Authenticode Code-Signing Script
# Made with ❤️ in 🇳🇵 by Alok - hello@aloks.com.np

param(
    [string]$FilePath = "dist\LaptopMigrator.exe",
    [string]$CertSubject = "CN=Alok Shrestha Code Signing",
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Authenticode Code-Signing ===" -ForegroundColor Cyan
Write-Host "Target: $FilePath" -ForegroundColor Cyan

if (-not (Test-Path $FilePath)) {
    Write-Warning "Target file '$FilePath' not found. Build the executable first."
    exit 1
}

# Find or generate self-signed certificate
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -eq $CertSubject } | Select-Object -First 1

if (-not $cert) {
    Write-Host "No existing code-signing certificate found with subject '$CertSubject'. Creating self-signed certificate..." -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $CertSubject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(5)
    Write-Host "Generated new certificate: $($cert.Thumbprint)" -ForegroundColor Green
} else {
    Write-Host "Found code-signing certificate: $($cert.Thumbprint)" -ForegroundColor Green
}

# Export public certificate for distribution/trust
$distDir = Split-Path -Path $FilePath -Parent
if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
}
$cerPath = Join-Path $distDir "AlokShresthaCodeSigning.cer"
Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
Write-Host "Public certificate exported to: $cerPath" -ForegroundColor Green
Write-Host "To trust this certificate and eliminate SmartScreen warnings, run as Administrator:" -ForegroundColor Gray
Write-Host "  certutil -addstore -f `"Root`" `"$cerPath`"" -ForegroundColor Cyan

# Sign binary
Write-Host "Signing executable with SHA256 and RFC 3161 timestamp..." -ForegroundColor Yellow
$sig = Set-AuthenticodeSignature -FilePath $FilePath -Certificate $cert -TimestampServer $TimestampServer -HashAlgorithm SHA256

if ($sig.Status -eq "Valid") {
    Write-Host "Successfully signed: $FilePath" -ForegroundColor Green
} else {
    Write-Warning "Signature completed with status: $($sig.StatusMessage)"
}
