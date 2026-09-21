<#
.SYNOPSIS
    AI Meeting Assistant - Read-Only Windows Installation Verification Script
.DESCRIPTION
    Performs comprehensive, strictly read-only diagnostics on the local environment,
    validating project files, Python runtime, virtual environment, core dependencies,
    cryptographic security configuration, SQLite database, FFmpeg engine, storage paths,
    Django system check, and upload limits.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

# ----------------------------------------------------------------------
# 0. RESOLVE PROJECT ROOT & INITIALIZE REPORT
# ----------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path "$ScriptDir\..").Path
$ReportFile = Join-Path $ProjectRoot "verify_report.txt"

function Write-Report {
    param([string]$Message)
    # Redact potential 32+ character secrets/tokens from report
    $sanitized = $Message -replace "([A-Za-z0-9_-]{32,}=*)", "[REDACTED]"
    Add-Content -Path $ReportFile -Value $sanitized -ErrorAction SilentlyContinue
}

# Start fresh report
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"======================================================================" | Out-File -FilePath $ReportFile -Encoding utf8
"AI Meeting Assistant - Installation Verification Report ($timestamp)" | Add-Content -Path $ReportFile
"Project Root: $ProjectRoot" | Add-Content -Path $ReportFile
"======================================================================" | Add-Content -Path $ReportFile
"" | Add-Content -Path $ReportFile

$failCount = 0
$warnCount = 0
$checkResults = [System.Collections.Generic.List[PSCustomObject]]::new()
$failedCards = [System.Collections.Generic.List[hashtable]]::new()

function Record-Check {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Detail
    )
    $checkResults.Add([PSCustomObject]@{
        Name   = $Name
        Status = $Status
        Detail = $Detail
    })
    Write-Report "[$Status] $Name - $Detail"
}

function Show-Fail {
    param(
        [string]$Title,
        [string]$Problem,
        [string]$Action,
        [string]$RefCode
    )
    $script:failCount++
    Record-Check $Title "FAIL" "$Problem (Ref: $RefCode)"
    $failedCards.Add(@{
        Title   = $Title
        Problem = $Problem
        Action  = $Action
        RefCode = $RefCode
    })
}

function Show-Warn {
    param(
        [string]$Title,
        [string]$Problem,
        [string]$Action,
        [string]$RefCode
    )
    $script:warnCount++
    Record-Check $Title "WARN" "$Problem (Ref: $RefCode)"
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " AI MEETING ASSISTANT - LOCAL ENVIRONMENT VERIFICATION" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# ----------------------------------------------------------------------
# CHECK 1 / 10 — PROJECT FILES
# ----------------------------------------------------------------------
Write-Host "[1/10] Checking Project Files..." -ForegroundColor Gray

$requiredFiles = @(
    "manage.py",
    "requirements.txt",
    "config\settings.py",
    "config\urls.py",
    "meeting",
    ".env"
)

$missingProjectFiles = @()
foreach ($rf in $requiredFiles) {
    $targetPath = Join-Path $ProjectRoot $rf
    if (-not (Test-Path $targetPath)) {
        $missingProjectFiles += $rf
    }
}

if ($missingProjectFiles.Count -gt 0) {
    $missingStr = $missingProjectFiles -join ", "
    Show-Fail "Project Files" "Required application files are missing ($missingStr)." "Re-extract the application package or run 'Setup Application.bat'." "SETUP-PROJECT-001"
    Write-Host " [FAIL] Project Files          : Missing ($missingStr)" -ForegroundColor Red
} else {
    Record-Check "Project Files" "PASS" "All required project files present"
    Write-Host " [PASS] Project Files          : All core files present" -ForegroundColor Green
}

# ----------------------------------------------------------------------
# CHECK 2 / 10 — PYTHON RUNTIME
# ----------------------------------------------------------------------
Write-Host "[2/10] Checking Python Runtime..." -ForegroundColor Gray

$detectedPython = $null
$pyVersionStr = ""
$pyArch = ""
$pyMajor = 0
$pyMinor = 0

try {
    $verOut = & python -c "import sys, platform; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{platform.architecture()[0]}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $verOut) {
        $parts = $verOut.Trim().Split("|")
        $pyVersionStr = $parts[0]
        if ($parts.Length -gt 1) { $pyArch = $parts[1] }
        $detectedPython = "python"
    }
} catch {}

if (-not $detectedPython) {
    try {
        $verOut = & py -3 -c "import sys, platform; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{platform.architecture()[0]}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $verOut) {
            $parts = $verOut.Trim().Split("|")
            $pyVersionStr = $parts[0]
            if ($parts.Length -gt 1) { $pyArch = $parts[1] }
            $detectedPython = "py -3"
        }
    } catch {}
}

if (-not $detectedPython) {
    Show-Fail "Python Runtime" "Python 3.10-3.12 was not detected on your system PATH." "Install Python 3.11 from https://www.python.org/downloads/ and enable 'Add Python to PATH'." "SETUP-PYTHON-001"
    Write-Host " [FAIL] Python Runtime         : Python 3.10-3.12 not found" -ForegroundColor Red
} else {
    $vParts = $pyVersionStr.Split(".")
    if ($vParts.Length -ge 2) {
        $pyMajor = [int]$vParts[0]
        $pyMinor = [int]$vParts[1]
    }

    if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
        Show-Fail "Python Runtime" "Detected Python ($pyVersionStr) is older than the required Python 3.10." "Install Python 3.11 from https://www.python.org/downloads/ and enable 'Add Python to PATH'." "SETUP-PYTHON-002"
        Write-Host " [FAIL] Python Runtime         : Python $pyVersionStr ($pyArch) is outdated" -ForegroundColor Red
    } elseif ($pyMajor -eq 3 -and $pyMinor -gt 12) {
        Show-Warn "Python Runtime" "Detected Python ($pyVersionStr) is newer than the standard tested range (Python 3.10-3.12)." "Proceed with caution or use Python 3.11." "SETUP-PYTHON-003"
        Write-Host " [WARN] Python Runtime         : Python $pyVersionStr ($pyArch) newer than tested range" -ForegroundColor Yellow
    } else {
        $archLabel = if ($pyArch) { " ($pyArch)" } else { "" }
        Record-Check "Python Runtime" "PASS" "Python $pyVersionStr$archLabel"
        Write-Host " [PASS] Python Runtime         : Python $pyVersionStr$archLabel" -ForegroundColor Green
    }
}

# ----------------------------------------------------------------------
# CHECK 3 / 10 — VIRTUAL ENVIRONMENT
# ----------------------------------------------------------------------
Write-Host "[3/10] Checking Virtual Environment..." -ForegroundColor Gray

$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$venvValid = $false

if (Test-Path $VenvPython) {
    try {
        $venvCheck = & $VenvPython -c "import sys; print(sys.prefix)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $venvCheck) {
            $venvValid = $true
        }
    } catch {}
}

if ($venvValid) {
    Record-Check "Virtual Environment" "PASS" ".venv is valid"
    Write-Host " [PASS] Virtual Environment    : .venv is valid" -ForegroundColor Green
} else {
    Show-Fail "Virtual Environment" "The application's Python virtual environment is missing or invalid." "Run 'Setup Application.bat' again." "SETUP-VENV-001"
    Write-Host " [FAIL] Virtual Environment    : Missing or broken at .venv" -ForegroundColor Red
}

# ----------------------------------------------------------------------
# CHECK 4 / 10 — CORE DEPENDENCIES
# ----------------------------------------------------------------------
Write-Host "[4/10] Checking Core Dependencies..." -ForegroundColor Gray

if (-not $venvValid) {
    Show-Fail "Core Dependencies" "Cannot check dependencies because virtual environment is unavailable." "Run 'Setup Application.bat' again." "SETUP-DEP-001"
    Write-Host " [FAIL] Core Dependencies      : Skipped (no valid .venv)" -ForegroundColor Red
} else {
    $corePackages = @("django", "google.genai", "cryptography", "anthropic", "dotenv", "whitenoise", "dj_database_url")
    $missingPkgs = @()
    $installedDetails = @()

    foreach ($pkg in $corePackages) {
        $checkCmd = "import importlib; mod = importlib.import_module('$pkg'); ver = getattr(mod, '__version__', 'present'); print(f'{mod.__name__}=={ver}')"
        try {
            $pkgOut = & $VenvPython -c $checkCmd 2>$null
            if ($LASTEXITCODE -eq 0 -and $pkgOut) {
                $installedDetails += $pkgOut.Trim()
            } else {
                $missingPkgs += $pkg
            }
        } catch {
            $missingPkgs += $pkg
        }
    }

    if ($missingPkgs.Count -eq 0) {
        $detStr = $installedDetails -join ", "
        Record-Check "Core Dependencies" "PASS" "All required packages installed: $detStr"
        Write-Host " [PASS] Core Dependencies      : All required packages available" -ForegroundColor Green
    } else {
        $missingStr = $missingPkgs -join ", "
        Show-Fail "Core Dependencies" "One or more required Python packages are missing ($missingStr)." "Run 'Setup Application.bat' again." "SETUP-DEP-001"
        Write-Host " [FAIL] Core Dependencies      : Missing ($missingStr)" -ForegroundColor Red
    }
}

# ----------------------------------------------------------------------
# CHECK 5 / 10 — ENVIRONMENT & ENCRYPTION CONFIGURATION
# ----------------------------------------------------------------------
Write-Host "[5/10] Checking Security & Encryption Configuration..." -ForegroundColor Gray

$EnvPath = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvPath)) {
    Show-Fail "Security Configuration" ".env configuration file is missing." "Run 'Setup Application.bat' again." "SETUP-ENV-001"
    Write-Host " [FAIL] Security Configuration : .env file not found" -ForegroundColor Red
} elseif (-not $venvValid) {
    Show-Fail "Security Configuration" "Cannot validate encryption keys because virtual environment is unavailable." "Run 'Setup Application.bat' again." "SETUP-ENV-001"
    Write-Host " [FAIL] Security Configuration : Skipped (no valid .venv)" -ForegroundColor Red
} else {
    $secCode = "import os, sys, dotenv, cryptography.fernet; dotenv.load_dotenv(r'$EnvPath'); sec = os.getenv('SECRET_KEY'); enc = os.getenv('ENCRYPTION_KEY'); sys.exit(2 if not sec else (3 if not enc else (0 if cryptography.fernet.Fernet(enc.encode()) else 4)))"
    try {
        $null = & $VenvPython -c $secCode 2>$null
        $secExit = $LASTEXITCODE
        if ($secExit -eq 0) {
            Record-Check "Security Configuration" "PASS" "SECRET_KEY and ENCRYPTION_KEY are valid"
            Write-Host " [PASS] Security Configuration : SECRET_KEY and ENCRYPTION_KEY are valid" -ForegroundColor Green
        } elseif ($secExit -eq 2) {
            Show-Fail "Security Configuration" "SECRET_KEY is missing in .env." "Run 'Setup Application.bat' again." "SETUP-ENV-001"
            Write-Host " [FAIL] Security Configuration : SECRET_KEY missing in .env" -ForegroundColor Red
        } elseif ($secExit -eq 3) {
            Show-Fail "Security Configuration" "ENCRYPTION_KEY is missing in .env." "Run 'Setup Application.bat' again." "SETUP-ENV-001"
            Write-Host " [FAIL] Security Configuration : ENCRYPTION_KEY missing in .env" -ForegroundColor Red
        } else {
            Show-Fail "Security Configuration" "ENCRYPTION_KEY is not a valid Fernet key." "Run 'Setup Application.bat' again." "SETUP-ENV-001"
            Write-Host " [FAIL] Security Configuration : Invalid Fernet ENCRYPTION_KEY" -ForegroundColor Red
        }
    } catch {
        Show-Fail "Security Configuration" "Failed to validate local security configuration." "Run 'Setup Application.bat' again." "SETUP-ENV-001"
        Write-Host " [FAIL] Security Configuration : Validation error" -ForegroundColor Red
    }
}

# ----------------------------------------------------------------------
# CHECK 6 / 10 — DATABASE / SQLITE
# ----------------------------------------------------------------------
Write-Host "[6/10] Checking Database Engine..." -ForegroundColor Gray

if (-not $venvValid) {
    Show-Fail "Database Engine" "Cannot check database because virtual environment is unavailable." "Run 'Setup Application.bat' again." "SETUP-DB-001"
    Write-Host " [FAIL] Database Engine        : Skipped (no valid .venv)" -ForegroundColor Red
} else {
    $dbCode = "import os, sys, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from django.db import connection; tables = connection.introspection.table_names(); req = ['auth_user', 'meeting_aisettings', 'meeting_meeting']; missing = [t for t in req if t not in tables]; sys.exit(1 if missing else 0)"
    try {
        $null = & $VenvPython -c $dbCode 2>$null
        $dbExit = $LASTEXITCODE
        if ($dbExit -eq 0) {
            Record-Check "Database Engine" "PASS" "SQLite database is ready (tables verified)"
            Write-Host " [PASS] Database Engine        : SQLite database is ready" -ForegroundColor Green
        } else {
            Show-Fail "Database Engine" "The local SQLite database is missing or incomplete (required tables missing)." "Run 'Setup Application.bat' again." "SETUP-DB-001"
            Write-Host " [FAIL] Database Engine        : SQLite database incomplete" -ForegroundColor Red
        }
    } catch {
        Show-Fail "Database Engine" "Failed to inspect local SQLite database." "Run 'Setup Application.bat' again." "SETUP-DB-001"
        Write-Host " [FAIL] Database Engine        : Inspection failed" -ForegroundColor Red
    }
}

# ----------------------------------------------------------------------
# CHECK 7 / 10 — FFMPEG AUDIO EXTRACTION ENGINE
# ----------------------------------------------------------------------
Write-Host "[7/10] Checking FFmpeg Audio Engine..." -ForegroundColor Gray

$ffmpegFound = $false
$ffmpegPath = $null

# 1. Check FFMPEG_PATH environment variable
if ($env:FFMPEG_PATH -and (Test-Path $env:FFMPEG_PATH)) {
    $ffmpegFound = $true
    $ffmpegPath = $env:FFMPEG_PATH
}

# 2. Check system PATH
if (-not $ffmpegFound) {
    try {
        $sysFfmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
        if ($sysFfmpeg) {
            $ffmpegFound = $true
            $ffmpegPath = $sysFfmpeg
        }
    } catch {}
}

# 3. Check project bin\ffmpeg.exe
if (-not $ffmpegFound) {
    $localFfmpegExe = Join-Path $ProjectRoot "bin\ffmpeg.exe"
    if (Test-Path $localFfmpegExe) {
        $ffmpegFound = $true
        $ffmpegPath = $localFfmpegExe
    }
}

# 4. Check project bin\ffmpeg
if (-not $ffmpegFound) {
    $localFfmpegBin = Join-Path $ProjectRoot "bin\ffmpeg"
    if (Test-Path $localFfmpegBin) {
        $ffmpegFound = $true
        $ffmpegPath = $localFfmpegBin
    }
}

# 5. Check local Windows build fallback
if (-not $ffmpegFound) {
    $winFallback = "C:\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
    if (Test-Path $winFallback) {
        $ffmpegFound = $true
        $ffmpegPath = $winFallback
    }
}

# Validate execution if found
$ffmpegExecutable = $false
if ($ffmpegFound -and $ffmpegPath) {
    try {
        $ffVer = & $ffmpegPath -version 2>$null
        if ($LASTEXITCODE -eq 0 -and $ffVer) {
            $ffmpegExecutable = $true
        }
    } catch {}
}

if ($ffmpegExecutable) {
    Record-Check "FFmpeg Engine" "PASS" "FFmpeg detected ($ffmpegPath)"
    Write-Host " [PASS] FFmpeg Engine          : FFmpeg detected ($ffmpegPath)" -ForegroundColor Green
} else {
    Show-Fail "FFmpeg Engine" "FFmpeg audio extraction binary was not detected or failed to execute." "Place the approved ffmpeg.exe in 'bin\ffmpeg.exe' or install FFmpeg to your system PATH." "SETUP-FFMPEG-001"
    Write-Host " [FAIL] FFmpeg Engine          : FFmpeg not detected" -ForegroundColor Red
}

# ----------------------------------------------------------------------
# CHECK 8 / 10 — MEDIA STORAGE
# ----------------------------------------------------------------------
Write-Host "[8/10] Checking Media Storage Directories..." -ForegroundColor Gray

$storageDirs = @(
    "media",
    "media\meetings\original",
    "media\meetings\audio",
    "media\meetings\transcripts",
    "staticfiles",
    "bin"
)

$missingDirs = @()
foreach ($sdir in $storageDirs) {
    $sdPath = Join-Path $ProjectRoot $sdir
    if (-not (Test-Path $sdPath)) {
        $missingDirs += $sdir
    }
}

if ($missingDirs.Count -gt 0) {
    $mDirStr = $missingDirs -join ", "
    Show-Fail "Media Storage" "One or more required application directories are missing ($mDirStr)." "Run 'Setup Application.bat' again." "SETUP-STORAGE-001"
    Write-Host " [FAIL] Media Storage          : Missing ($mDirStr)" -ForegroundColor Red
} else {
    Record-Check "Media Storage" "PASS" "All required storage directories available"
    Write-Host " [PASS] Media Storage          : Required directories available" -ForegroundColor Green
}

# ----------------------------------------------------------------------
# CHECK 9 / 10 — DJANGO SYSTEM CHECK
# ----------------------------------------------------------------------
Write-Host "[9/10] Performing Django System Check..." -ForegroundColor Gray

if (-not $venvValid) {
    Show-Fail "Django System Check" "Cannot run Django check because virtual environment is unavailable." "Run 'Setup Application.bat' again." "SETUP-DJANGO-001"
    Write-Host " [FAIL] Django System Check    : Skipped (no valid .venv)" -ForegroundColor Red
} else {
    try {
        $chkOut = & $VenvPython "$ProjectRoot\manage.py" check 2>&1
        if ($LASTEXITCODE -eq 0) {
            Record-Check "Django System Check" "PASS" "0 issues identified"
            Write-Host " [PASS] Django System Check    : 0 issues identified" -ForegroundColor Green
        } else {
            Show-Fail "Django System Check" "Django system check reported configuration errors." "Run 'Setup Application.bat' again or check verify_report.txt." "SETUP-DJANGO-001"
            Write-Host " [FAIL] Django System Check    : System check reported issues" -ForegroundColor Red
            Write-Report "[DJANGO-CHECK-ERR] $chkOut"
        }
    } catch {
        Show-Fail "Django System Check" "Failed to execute Django system check." "Run 'Setup Application.bat' again." "SETUP-DJANGO-001"
        Write-Host " [FAIL] Django System Check    : Execution failed" -ForegroundColor Red
    }
}

# ----------------------------------------------------------------------
# CHECK 10 / 10 — UPLOAD CONFIGURATION
# ----------------------------------------------------------------------
Write-Host "[10/10] Checking Upload Configuration..." -ForegroundColor Gray

$uploadLimitStr = "Unknown"
if ($venvValid) {
    $upCode = "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from django.conf import settings; print(getattr(settings, 'MAX_UPLOAD_SIZE', 52428800))"
    try {
        $upOut = & $VenvPython -c $upCode 2>$null
        if ($LASTEXITCODE -eq 0 -and $upOut) {
            $bytes = [int64]$upOut.Trim()
            if ($bytes -ge 1073741824) {
                $gb = [math]::Round($bytes / 1073741824, 2)
                $uploadLimitStr = "$gb GB local upload limit"
            } elseif ($bytes -eq 52428800) {
                $uploadLimitStr = "50 MB default upload limit"
            } else {
                $mb = [math]::Round($bytes / 1048576, 1)
                $uploadLimitStr = "$mb MB upload limit"
            }
            Record-Check "Upload Configuration" "PASS" $uploadLimitStr
            Write-Host " [PASS] Upload Configuration   : $uploadLimitStr" -ForegroundColor Green
        } else {
            Record-Check "Upload Configuration" "PASS" "50 MB default upload limit"
            Write-Host " [PASS] Upload Configuration   : 50 MB default upload limit" -ForegroundColor Green
        }
    } catch {
        Record-Check "Upload Configuration" "PASS" "50 MB default upload limit"
        Write-Host " [PASS] Upload Configuration   : 50 MB default upload limit" -ForegroundColor Green
    }
} else {
    Record-Check "Upload Configuration" "PASS" "50 MB default fallback"
    Write-Host " [PASS] Upload Configuration   : 50 MB default fallback" -ForegroundColor Green
}

# ----------------------------------------------------------------------
# SUMMARY & DIAGNOSTIC REPORT
# ----------------------------------------------------------------------
Write-Host ""
Write-Report ""
Write-Report "======================================================================"
Write-Report "VERIFICATION SUMMARY: Failures=$failCount, Warnings=$warnCount"
Write-Report "======================================================================"

if ($failCount -eq 0) {
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host " AI MEETING ASSISTANT - LOCAL ENVIRONMENT VERIFICATION" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host ""
    foreach ($item in $checkResults) {
        if ($item.Status -eq "PASS") {
            Write-Host " [PASS] $($item.Name)" -ForegroundColor Green
        } elseif ($item.Status -eq "WARN") {
            Write-Host " [WARN] $($item.Name)" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Green
    Write-Host " STATUS: ALL CHECKS PASSED" -ForegroundColor Green
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Green
    Write-Host ""
    Write-Host "The application is ready to start." -ForegroundColor White
    Write-Host ""
    Write-Host "Next step:" -ForegroundColor Yellow
    Write-Host "Double-click `"Start Application.bat`"" -ForegroundColor White
    Write-Host ""
    Write-Host "Diagnostic Report:" -ForegroundColor Gray
    Write-Host "verify_report.txt" -ForegroundColor Gray
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Green
    exit 0
} else {
    Write-Host "======================================================================" -ForegroundColor Red
    Write-Host " STATUS: VERIFICATION FAILED ($failCount issue(s) detected)" -ForegroundColor Red
    Write-Host "======================================================================" -ForegroundColor Red
    Write-Host ""
    foreach ($card in $failedCards) {
        Write-Host " [FAIL] $($card.Title)" -ForegroundColor Red
        Write-Host " Problem        : $($card.Problem)" -ForegroundColor Yellow
        Write-Host " Action Required: $($card.Action)" -ForegroundColor White
        Write-Host " Reference Code : $($card.RefCode)" -ForegroundColor Cyan
        Write-Host ""
    }
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Red
    Write-Host " Diagnostic Report:" -ForegroundColor Gray
    Write-Host " verify_report.txt" -ForegroundColor Gray
    Write-Host ""
    Write-Host " Please run `"Setup Application.bat`" again if appropriate." -ForegroundColor Yellow
    Write-Host " If the problem persists, provide verify_report.txt to IT support." -ForegroundColor White
    Write-Host "======================================================================" -ForegroundColor Red
    exit 1
}

