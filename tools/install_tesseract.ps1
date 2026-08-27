# install_tesseract.ps1
# 安装 Tesseract OCR 引擎 + 中文语言包 chi_sim，解锁私有图书馆「扫描版 PDF」的正文抽取。
# 用法（在 F:\my-library 目录，以管理员或普通用户 PowerShell 运行）：
#   powershell -ExecutionPolicy Bypass -File tools/install_tesseract.ps1
# 装完验证：tesseract --list-langs  应看到 chi_sim
# 之后重抽扫描版：python tools/run_extract_full.py ocr

$ErrorActionPreference = "Stop"

function Find-Tesseract {
    $t = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($t) { return $t.Source }
    # 常见安装路径兜底
    $guess = @(
        "C:\Program Files\Tesseract-OCR\tesseract.exe",
        "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
    )
    foreach ($g in $guess) { if (Test-Path $g) { return $g } }
    return $null
}

$tess = Find-Tesseract
if ($tess) {
    Write-Host "✅ 已检测到 tesseract: $tess"
} else {
    Write-Host "🔄 未检测到 tesseract，开始安装..."
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        Write-Host "   使用 winget 安装 UB-Mannheim.TesseractOCR ..."
        winget install --id UB-Mannheim.TesseractOCR -e --source winget `
            --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "❌ 未找到 winget，无法自动安装。请手动安装后重跑本脚本："
        Write-Host "   方案A(推荐): 管理员 PowerShell 执行  Install-Module ChocolateyGet -Force; choco install tesseract"
        Write-Host "   方案B: 浏览器下载 https://github.com/UB-Mannheim/tesseract/releases 的 tesseract-ocr-w64-setup-*.exe 双击安装(勾选添加到PATH)"
        exit 1
    }
    # 安装后刷新 PATH（winget 可能只写 Machine PATH，需重新读取）
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" `
              + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $tess = Find-Tesseract
    if (-not $tess) {
        Write-Host "⚠️ 安装似乎完成但 PATH 未生效，请重开 PowerShell 后重跑本脚本。"
        exit 1
    }
    Write-Host "✅ tesseract 安装成功: $tess"
}

# ---- 下载中文语言包 chi_sim.traineddata（多镜像兜底，规避国内 GitHub 不稳定）----
$tessDir  = Split-Path $tess
$tessdata = Join-Path $tessDir "tessdata"
if (-not (Test-Path $tessdata)) { New-Item -ItemType Directory -Path $tessdata | Out-Null }
$chi = Join-Path $tessdata "chi_sim.traineddata"

$haveChi = $false
if (Test-Path $chi) {
    Write-Host "✅ chi_sim 已存在: $chi"
    $haveChi = $true
} else {
    $urls = @(
        "https://ghproxy.com/https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata",
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/chi_sim.traineddata",
        "https://kkgithub.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata"
    )
    foreach ($u in $urls) {
        try {
            Write-Host "   ↓ 下载 chi_sim ($u)"
            Invoke-WebRequest -Uri $u -OutFile $chi -TimeoutSec 180 -ErrorAction Stop
            if ((Get-Item $chi).Length -gt 1MB) { $haveChi = $true; break }
            else { Remove-Item $chi -Force }
        } catch {
            Write-Host "   镜像失败: $($_.Exception.Message)"
        }
    }
}

if (-not $haveChi) {
    Write-Host "❌ chi_sim 下载失败（网络受限）。可手动下载后放到: $tessdata"
    Write-Host "   下载地址: https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata"
    exit 1
}

# ---- 验证 ----
Write-Host "🔍 验证已装语言包:"
$langs = & $tess --list-langs 2>&1
$langs | ForEach-Object { Write-Host "   $_" }
if ($langs -match "chi_sim") {
    Write-Host ""
    Write-Host "🎉 安装完成！扫描版 PDF 的 OCR 已解锁。"
    Write-Host "➡️ 下一步重抽扫描版：在 F:\my-library 目录运行"
    Write-Host "      python tools/run_extract_full.py ocr"
    Write-Host "   (仅重抽正文<=200字的PDF；>50MB大文件仍跳过，需另行处理)"
} else {
    Write-Host "⚠️ chi_sim 未在语言列表中出现，请检查 tessdata 路径: $tessdata"
    exit 1
}
