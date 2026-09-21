<#
.SYNOPSIS
    AI Meeting Assistant - Automated Windows Setup Script
.DESCRIPTION
    Automates virtual environment creation, dependency installation, cryptographic
    key generation, local SQLite setup, directory creation, and system validation.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# Determine project root dynamically from this script's location
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path "$ScriptDir\..").Path

# Initialize setup log
$LogFile = Join-Path $ProjectRoot "setup_log.txt"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    # Basic redaction to guarantee secrets never enter log
    $sanitized = $Message -replace "([A-Za-z0-9_-]{32,}=*)", "[REDACTED]"
    Add-Content -Path $LogFile -Value "[$timestamp] $sanitized" -ErrorAction SilentlyContinue
}

# Start log
"======================================================================" | Out-File -FilePath $LogFile -Encoding utf8
"AI Meeting Assistant - Setup Log ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))" | Add-Content -Path $LogFile
"Project Root: $ProjectRoot" | Add-Content -Path $LogFile
"======================================================================" | Add-Content -Path $LogFile

function Show-FailCard {
    param(
        [string]$Title,
        [string]$Problem,
        [string]$Action,
        [string]$RefCode
    )
    Write-Host ""
    Write-Host " [FAIL] $Title" -ForegroundColor Red
    Write-Host ""
    Write-Host " Problem:" -ForegroundColor Yellow
    Write-Host " $Problem" -ForegroundColor White
    Write-Host ""
    Write-Host " Action Required:" -ForegroundColor Yellow
    Write-Host " $Action" -ForegroundColor White
    Write-Host ""
    Write-Host " Reference Code: $RefCode" -ForegroundColor Cyan
    Write-Host " Diagnostic Log: setup_log.txt" -ForegroundColor Gray
    Write-Host ""
    Write-Log "[FAIL] $Title - Problem: $Problem | Action: $Action | Ref: $RefCode"
}

function Show-WarnCard {
    param(
        [string]$Title,
        [string]$Problem,
        [string]$Action,
        [string]$RefCode
    )
    Write-Host ""
    Write-Host " [WARN] $Title" -ForegroundColor Yellow
    Write-Host ""
    Write-Host " Note:" -ForegroundColor Yellow
    Write-Host " $Problem" -ForegroundColor White
    Write-Host ""
    Write-Host " Recommended Action:" -ForegroundColor Yellow
    Write-Host " $Action" -ForegroundColor White
    Write-Host ""
    Write-Host " Reference Code: $RefCode" -ForegroundColor Cyan
    Write-Host ""
    Write-Log "[WARN] $Title - Note: $Problem | Action: $Action | Ref: $RefCode"
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " AI MEETING ASSISTANT - ENVIRONMENT SETUP" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# =====================================================================
# STEP 1 — CHECK PYTHON RUNTIME
# =====================================================================
Write-Host " -> Checking Python runtime..." -ForegroundColor Gray

$detectedPython = $null
$detectedPythonCmd = $null
$pyVersionStr = ""
$pyMajor = 0
$pyMinor = 0

# Check python.exe first
try {
    $verOut = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $verOut) {
        $detectedPython = "python"
        $detectedPythonCmd = @("python")
        $pyVersionStr = $verOut.Trim()
    }
} catch {}

# Check py.exe fallback if python not found
if (-not $detectedPython) {
    try {
        $verOut = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $verOut) {
            $detectedPython = "py -3"
            $detectedPythonCmd = @("py", "-3")
            $pyVersionStr = $verOut.Trim()
        }
    } catch {}
}

if (-not $detectedPython) {
    Show-FailCard "Python Runtime" "Python 3.10-3.12 was not found on your system PATH." "Download and install Python 3.11 from https://www.python.org/downloads/ and make sure to check 'Add Python to PATH'." "SETUP-PYTHON-001"
    exit 1
}

$parts = $pyVersionStr.Split(".")
if ($parts.Length -ge 2) {
    $pyMajor = [int]$parts[0]
    $pyMinor = [int]$parts[1]
}

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Show-FailCard "Python Runtime" "Detected Python version ($pyVersionStr) is older than the required Python 3.10." "Please install Python 3.11 from https://www.python.org/downloads/ and ensure 'Add Python to PATH' is checked." "SETUP-PYTHON-002"
    exit 1
}

if ($pyMajor -eq 3 -and $pyMinor -gt 12) {
    Show-WarnCard "Python Version Compatibility" "Detected Python version ($pyVersionStr) is newer than the standard tested range (Python 3.10-3.12)." "Setup will proceed, but if third-party packages fail to install, please install Python 3.11." "SETUP-PYTHON-003"
}

Write-Host " [PASS] Python Runtime         : Python $pyVersionStr ($detectedPython)" -ForegroundColor Green
Write-Log "Python runtime detected: Python $pyVersionStr via $detectedPython"

# =====================================================================
# STEP 2 — VIRTUAL ENVIRONMENT (.venv)
# =====================================================================
Write-Host " -> Verifying virtual environment..." -ForegroundColor Gray

$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$reusedVenv = $false

if (Test-Path $VenvPython) {
    try {
        $testOut = & $VenvPython -c "import sys; print(sys.prefix)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $reusedVenv = $true
            Write-Host " [PASS] Virtual Environment    : Reusing existing .venv" -ForegroundColor Green
            Write-Log "Reused existing virtual environment at $VenvDir"
        }
    } catch {}
}

if (-not $reusedVenv) {
    Write-Host " -> Creating virtual environment at .venv..." -ForegroundColor Gray
    try {
        if ($detectedPythonCmd.Length -gt 1) {
            & $detectedPythonCmd[0] $detectedPythonCmd[1] -m venv "$VenvDir" 2>> $LogFile
        } else {
            & $detectedPythonCmd[0] -m venv "$VenvDir" 2>> $LogFile
        }

        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
            throw "Virtual environment creation failed (exit code: $LASTEXITCODE)."
        }
        Write-Host " [PASS] Virtual Environment    : Created new .venv" -ForegroundColor Green
        Write-Log "Created new virtual environment at $VenvDir"
    } catch {
        Show-FailCard "Virtual Environment" "Failed to create Python virtual environment at $VenvDir." "Ensure you have write permissions in this folder and Python venv package is installed." "SETUP-VENV-001"
        exit 1
    }
}

# =====================================================================
# STEP 3 — INSTALL DEPENDENCIES (requirements.txt)
# =====================================================================
Write-Host " -> Installing dependencies from requirements.txt..." -ForegroundColor Gray

$ReqFile = Join-Path $ProjectRoot "requirements.txt"
if (-not (Test-Path $ReqFile)) {
    Show-FailCard "Dependencies" "requirements.txt was not found in the project root." "Ensure all project files were extracted completely from the ZIP archive." "SETUP-DEP-002"
    exit 1
}

try {
    # Upgrade pip silently
    & $VenvPython -m pip install --quiet --upgrade pip 2>> $LogFile

    # Install requirements
    $pipOut = & $VenvPython -m pip install -r "$ReqFile" 2>&1
    Write-Log "Pip output: $pipOut"

    if ($LASTEXITCODE -ne 0) {
        throw "Pip returned error code $LASTEXITCODE"
    }

    Write-Host " [PASS] Python Dependencies    : All requirements satisfied" -ForegroundColor Green
    Write-Log "Dependencies successfully installed from $ReqFile"
} catch {
    Show-FailCard "Dependencies" "Failed to install Python packages from requirements.txt." "Check your internet connection and verify that antivirus is not blocking pip downloads." "SETUP-DEP-001"
    exit 1
}

# =====================================================================
# STEP 4 — CREATE / PRESERVE LOCAL .ENV
# =====================================================================
Write-Host " -> Checking local environment configuration (.env)..." -ForegroundColor Gray

$EnvFile = Join-Path $ProjectRoot ".env"

if (Test-Path $EnvFile) {
    Write-Host " [PASS] Local Environment (.env): Preserved existing configuration" -ForegroundColor Green
    Write-Log "Preserved existing .env configuration file"
} else {
    Write-Host " -> Generating new local .env configuration..." -ForegroundColor Gray
    try {
        $createEnvCode = "import secrets, sys; from cryptography.fernet import Fernet; sec = secrets.token_urlsafe(50); enc = Fernet.generate_key().decode(); content = f'''# ==============================================================================\n# AI Meeting Assistant - Local Windows Configuration\n# Auto-generated by Setup Application.bat\n# ==============================================================================\nSECRET_KEY={sec}\nENCRYPTION_KEY={enc}\nDEBUG=True\nALLOWED_HOSTS=localhost,127.0.0.1\nCSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000\nDATABASE_URL=sqlite:///db.sqlite3\nMAX_UPLOAD_SIZE=2147483648\n'''; open(sys.argv[1], 'w', encoding='utf-8').write(content)"
        & $VenvPython -c $createEnvCode "$EnvFile"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $EnvFile)) {
            throw "Failed to generate .env"
        }
        Write-Host " [PASS] Local Environment (.env): Generated new configuration (2 GB upload limit)" -ForegroundColor Green
        Write-Log "Generated new local .env with SQLite and 2 GB upload limit"
    } catch {
        Show-FailCard "Local Environment (.env)" "Failed to generate local .env security configuration." "Ensure write permissions in the project folder and retry Setup." "SETUP-ENV-001"
        exit 1
    }
}

# =====================================================================
# STEP 5 — CREATE REQUIRED DIRECTORIES
# =====================================================================
Write-Host " -> Verifying required project directories..." -ForegroundColor Gray

$requiredDirs = @("media", "media\meetings\original", "media\meetings\audio", "media\meetings\transcripts", "staticfiles", "bin")
foreach ($dir in $requiredDirs) {
    $dirPath = Join-Path $ProjectRoot $dir
    if (-not (Test-Path $dirPath)) {
        New-Item -ItemType Directory -Path $dirPath -Force | Out-Null
        Write-Log "Created directory: $dir"
    }
}

Write-Host " [PASS] Storage Directories    : media, staticfiles, bin ready" -ForegroundColor Green

# =====================================================================
# STEP 6 — CHECK FFMPEG ENGINE
# =====================================================================
Write-Host " -> Checking FFmpeg audio extraction engine..." -ForegroundColor Gray

$ffmpegFound = $false
$ffmpegPath = $null

# 1. Check project-local bin/ffmpeg.exe
$localFfmpeg = Join-Path $ProjectRoot "bin\ffmpeg.exe"
if (Test-Path $localFfmpeg) {
    $ffmpegFound = $true
    $ffmpegPath = $localFfmpeg
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

# 3. Check FFMPEG_PATH environment variable
if (-not $ffmpegFound -and $env:FFMPEG_PATH -and (Test-Path $env:FFMPEG_PATH)) {
    $ffmpegFound = $true
    $ffmpegPath = $env:FFMPEG_PATH
}

if ($ffmpegFound) {
    Write-Host " [PASS] FFmpeg Audio Engine    : Detected ($ffmpegPath)" -ForegroundColor Green
    Write-Log "FFmpeg detected at: $ffmpegPath"
} else {
    Show-WarnCard "FFmpeg Audio Engine" "FFmpeg audio extraction executable was not detected on your system or in the project 'bin' folder." "Download FFmpeg essentials from https://www.gyan.dev/ffmpeg/builds/ and place 'ffmpeg.exe' inside the 'bin' folder ($ProjectRoot\bin\ffmpeg.exe)." "SETUP-FFMPEG-001"
}

# =====================================================================
# STEP 7 — DJANGO DATABASE MIGRATIONS (SQLite)
# =====================================================================
Write-Host " -> Running database setup and migrations..." -ForegroundColor Gray

try {
    $migOut = & $VenvPython "$ProjectRoot\manage.py" migrate --noinput 2>&1
    Write-Log "Migration output: $migOut"

    if ($LASTEXITCODE -ne 0) {
        throw "Migration returned exit code $LASTEXITCODE"
    }

    Write-Host " [PASS] Database / SQLite      : db.sqlite3 migrated successfully" -ForegroundColor Green
    Write-Log "Database migrations applied successfully"
} catch {
    Show-FailCard "Database Setup" "Failed to run SQLite database migrations." "Check write permissions in the project root and inspect setup_log.txt." "SETUP-DB-001"
    exit 1
}

# =====================================================================
# STEP 8 — DJANGO SYSTEM VALIDATION CHECK
# =====================================================================
Write-Host " -> Performing Django system check..." -ForegroundColor Gray

try {
    $chkOut = & $VenvPython "$ProjectRoot\manage.py" check 2>&1
    Write-Log "Django check output: $chkOut"

    if ($LASTEXITCODE -ne 0) {
        throw "Django check returned exit code $LASTEXITCODE"
    }

    Write-Host " [PASS] Django System Check    : 0 issues identified" -ForegroundColor Green
    Write-Log "Django system check passed with 0 issues"
} catch {
    Show-FailCard "Django Configuration" "Django system check identified configuration errors." "Inspect setup_log.txt for configuration diagnostic details." "SETUP-DJANGO-001"
    exit 1
}

# =====================================================================
# STEP 9 — SUCCESS SUMMARY
# =====================================================================
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host " AI MEETING ASSISTANT - SETUP COMPLETED SUCCESSFULLY" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
Write-Host " [PASS] Python Runtime" -ForegroundColor Green
Write-Host " [PASS] Virtual Environment" -ForegroundColor Green
Write-Host " [PASS] Dependencies" -ForegroundColor Green
Write-Host " [PASS] Local Environment" -ForegroundColor Green
Write-Host " [PASS] Database / SQLite" -ForegroundColor Green
Write-Host " [PASS] Required Directories" -ForegroundColor Green
Write-Host " [PASS] Django System Check" -ForegroundColor Green
if ($ffmpegFound) {
    Write-Host " [PASS] FFmpeg Audio Engine" -ForegroundColor Green
} else {
    Write-Host " [WARN] FFmpeg Audio Engine (Action Required: place ffmpeg.exe in bin\)" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "----------------------------------------------------------------------" -ForegroundColor Cyan
Write-Host " Local upload limit : 2 GB" -ForegroundColor White
Write-Host " Database Engine    : SQLite (db.sqlite3)" -ForegroundColor White
Write-Host " Application State  : Ready" -ForegroundColor White
Write-Host "----------------------------------------------------------------------" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next step:" -ForegroundColor Yellow
Write-Host "Double-click `"Verify Installation.bat`"" -ForegroundColor White
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green

Write-Log "Setup script finished successfully with exit code 0"
exit 0

