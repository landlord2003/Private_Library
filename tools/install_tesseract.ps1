# install_tesseract.ps1
# Install Tesseract OCR engine + Chinese language pack (chi_sim) to unlock
# text extraction for scanned PDFs in the private library.
# Usage (run on the host machine, in F:\my-library):
#   powershell -ExecutionPolicy Bypass -File tools/install_tesseract.ps1
# Verify:  tesseract --list-langs   (should include chi_sim)
# Then OCR scanned PDFs:  python tools/run_extract_full.py ocr

$ErrorActionPreference = "Stop"

function Find-Tesseract {
    $t = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($t) { return $t.Source }
    $guess = @(
        "C:\Program Files\Tesseract-OCR\tesseract.exe",
        "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
    )
    foreach ($g in $guess) { if (Test-Path $g) { return $g } }
    return $null
}

$tess = Find-Tesseract
if ($tess) {
    Write-Host "tesseract already installed: $tess"
} else {
    Write-Host "tesseract not found, installing via winget ..."
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        winget install --id UB-Mannheim.TesseractOCR -e --source winget `
            --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "ERROR: winget not found. Install manually then re-run this script:"
        Write-Host "  Option A: in admin PowerShell run  choco install tesseract"
        Write-Host "  Option B: download tesseract-ocr-w64-setup-*.exe from"
        Write-Host "           https://github.com/UB-Mannheim/tesseract/releases and run it (tick Add to PATH)"
        exit 1
    }
    # Refresh PATH from registry so the new install is visible in this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" `
              + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $tess = Find-Tesseract
    if (-not $tess) {
        Write-Host "WARN: install finished but tesseract not on PATH. Re-open PowerShell and re-run."
        exit 1
    }
    Write-Host "tesseract installed: $tess"
}

# ---- Download Chinese language pack chi_sim.traineddata (mirror fallback) ----
$tessDir  = Split-Path $tess
$tessdata = Join-Path $tessDir "tessdata"
if (-not (Test-Path $tessdata)) { New-Item -ItemType Directory -Path $tessdata | Out-Null }
$chi = Join-Path $tessdata "chi_sim.traineddata"

$haveChi = $false
if (Test-Path $chi) {
    Write-Host "chi_sim already present: $chi"
    $haveChi = $true
} else {
    $urls = @(
        "https://kkgithub.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata",
        "https://ghproxy.com/https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata",
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/chi_sim.traineddata"
    )
    foreach ($u in $urls) {
        try {
            Write-Host "downloading chi_sim ($u)"
            Invoke-WebRequest -Uri $u -OutFile $chi -TimeoutSec 180 -ErrorAction Stop
            if ((Get-Item $chi).Length -gt 1MB) { $haveChi = $true; break }
            else { Remove-Item $chi -Force }
        } catch {
            Write-Host "mirror failed: $($_.Exception.Message)"
        }
    }
}

if (-not $haveChi) {
    Write-Host "ERROR: chi_sim download failed (network restricted)."
    Write-Host "  Manual: download https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata"
    Write-Host "  and place it in: $tessdata"
    exit 1
}

# ---- Verify ----
Write-Host "verifying installed languages:"
$langs = & $tess --list-langs 2>&1
$langs | ForEach-Object { Write-Host "   $_" }
if ($langs -match "chi_sim") {
    Write-Host ""
    Write-Host "DONE. Scanned-PDF OCR is now unlocked."
    Write-Host "Next, re-extract scanned books from F:\my-library:"
    Write-Host "    python tools/run_extract_full.py ocr"
    Write-Host "  (only re-extracts PDFs whose text <= 200 chars; >50MB files are still skipped)"
} else {
    Write-Host "WARN: chi_sim not in the language list. Check tessdata path: $tessdata"
    exit 1
}
