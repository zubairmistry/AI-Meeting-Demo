<#
.SYNOPSIS
    AI Meeting Assistant - Automated Windows Setup Script
.DESCRIPTION
    Automates Python runtime discovery, self-healing side-by-side Python 3.11 installation,
    virtual environment creation/recreation, dependency installation, cryptographic key generation,
    local SQLite database setup, directory creation, automated FFmpeg engine acquisition,
    and Django system validation.
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
# HELPER FUNCTIONS: PYTHON DISCOVERY & SIDE-BY-SIDE INSTALLATION
# =====================================================================

function Get-PythonInfo {
    param([string]$ExePath, [string]$Source)
    if (-not (Test-Path $ExePath)) { return $null }
    try {
        $verOut = & $ExePath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $verOut) {
            $verStr = $verOut.Trim()
            $parts = $verStr.Split(".")
            if ($parts.Length -ge 2) {
                $major = [int]$parts[0]
                $minor = [int]$parts[1]
                $micro = if ($parts.Length -ge 3) { [int]$parts[2] } else { 0 }
                $isComp = ($major -eq 3 -and ($minor -ge 10 -and $minor -le 12))
                $prio = 99
                if ($major -eq 3) {
                    if ($minor -eq 11) { $prio = 1 }
                    elseif ($minor -eq 12) { $prio = 2 }
                    elseif ($minor -eq 10) { $prio = 3 }
                }
                return [PSCustomObject]@{
                    Path         = $ExePath
                    Version      = $verStr
                    Major        = $major
                    Minor        = $minor
                    Micro        = $micro
                    IsCompatible = $isComp
                    Priority     = $prio
                    Source       = $Source
                }
            }
        }
    } catch {}
    return $null
}

function Discover-PythonInterpreters {
    $discovered = [System.Collections.Generic.List[PSCustomObject]]::new()
    $seenPaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    # 1. Check py launcher for specific compatible versions (3.11, 3.12, 3.10, and default 3)
    foreach ($v in @("3.11", "3.12", "3.10", "3")) {
        try {
            $p = & py -$v -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) {
                $trimmed = $p.Trim()
                if (-not $seenPaths.Contains($trimmed)) {
                    $info = Get-PythonInfo -ExePath $trimmed -Source "py -$v"
                    if ($info) {
                        $discovered.Add($info)
                        $seenPaths.Add($trimmed) | Out-Null
                    }
                }
            }
        } catch {}
    }

    # 2. Inspect 'py -0p' to locate all registered interpreters
    try {
        $pyList = & py -0p 2>$null
        if ($LASTEXITCODE -eq 0 -and $pyList) {
            foreach ($line in $pyList) {
                if ($line -match '([A-Za-z]:\\[^"]+\.exe)') {
                    $foundPath = $matches[1].Trim()
                    if (-not $seenPaths.Contains($foundPath)) {
                        $info = Get-PythonInfo -ExePath $foundPath -Source "py -0p"
                        if ($info) {
                            $discovered.Add($info)
                            $seenPaths.Add($foundPath) | Out-Null
                        }
                    }
                }
            }
        }
    } catch {}

    # 3. Check standard Windows Python installation directories
    $knownLocations = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python310\python.exe",
        "C:\Python311\python.exe",
        "C:\Python312\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($loc in $knownLocations) {
        if ((Test-Path $loc) -and (-not $seenPaths.Contains($loc))) {
            $info = Get-PythonInfo -ExePath $loc -Source "StandardPath"
            if ($info) {
                $discovered.Add($info)
                $seenPaths.Add($loc) | Out-Null
            }
        }
    }

    # 4. Check system PATH python.exe (excluding WindowsApps store stubs)
    try {
        $pathCmds = Get-Command python.exe -All -ErrorAction SilentlyContinue
        foreach ($cmd in $pathCmds) {
            $src = $cmd.Source
            if ($src -and (Test-Path $src) -and (-not $seenPaths.Contains($src)) -and ($src -notmatch "WindowsApps")) {
                $info = Get-PythonInfo -ExePath $src -Source "SystemPATH"
                if ($info) {
                    $discovered.Add($info)
                    $seenPaths.Add($src) | Out-Null
                }
            }
        }
    } catch {}

    return $discovered
}

function Install-Python311SideBySide {
    Write-Host " -> Attempting automated side-by-side installation of Python 3.11..." -ForegroundColor Yellow
    Write-Log "Initiating side-by-side installation of Python 3.11"

    # Strategy A: Windows Package Manager (winget)
    $hasWinget = $false
    try {
        $wingetVer = & winget --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $wingetVer) { $hasWinget = $true }
    } catch {}

    if ($hasWinget) {
        Write-Host " -> Installing Python 3.11 via Windows Package Manager (winget)..." -ForegroundColor Gray
        Write-Log "Executing: winget install --id Python.Python.3.11 --exact --source winget --accept-package-agreements --accept-source-agreements --silent"
        try {
            $proc = Start-Process -FilePath "winget" -ArgumentList "install --id Python.Python.3.11 --exact --source winget --accept-package-agreements --accept-source-agreements --silent" -Wait -PassThru -NoNewWindow
            Write-Log "winget exit code: $($proc.ExitCode)"
            if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 1 -or $proc.ExitCode -eq -1978335189) { # 0=success, 1=success/reboot, -1978335189=already installed
                Start-Sleep -Seconds 2
                return $true
            }
        } catch {
            Write-Log "winget install threw an exception: $($_.Exception.Message)"
        }
    }

    # Strategy B: Direct official Python.org installer download & per-user quiet install
    Write-Host " -> Downloading official Python 3.11 installer from python.org..." -ForegroundColor Gray
    $installerUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-3.11.9-amd64.exe"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -TimeoutSec 90 -UseBasicParsing -ErrorAction Stop
        Write-Log "Downloaded Python 3.11 installer to $installerPath"

        Write-Host " -> Installing Python 3.11 silently (per-user, non-destructive)..." -ForegroundColor Gray
        # Quiet per-user installation without overriding default launcher associations or global PATH
        $installArgs = "/quiet InstallAllUsers=0 PrependPath=0 Include_test=0 Include_pip=1 Include_launcher=1 SimpleInstall=1"
        $instProc = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru -NoNewWindow
        Write-Log "python installer exit code: $($instProc.ExitCode)"
        Start-Sleep -Seconds 3

        if ($instProc.ExitCode -eq 0 -or $instProc.ExitCode -eq 3010) {
            return $true
        }
    } catch {
        Write-Log "Direct Python installer download/install failed: $($_.Exception.Message)"
    } finally {
        if (Test-Path $installerPath) { Remove-Item -Path $installerPath -Force -ErrorAction SilentlyContinue }
    }

    return $false
}

# =====================================================================
# STEP 1 — CHECK PYTHON RUNTIME & SELF-HEAL IF UNSUPPORTED
# =====================================================================
Write-Host " -> Checking Python runtimes on system..." -ForegroundColor Gray

# Record global PATH python version for diagnostic reporting
$globalVerStr = "None"
try {
    $gOut = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $gOut) {
        $globalVerStr = $gOut.Trim()
    }
} catch {}

$discovered = Discover-PythonInterpreters
$compatible = $discovered | Where-Object { $_.IsCompatible } | Sort-Object Priority

if (-not $compatible) {
    # Check if an incompatible runtime exists (e.g., Python 3.14 or 3.13)
    $incompatible = $discovered | Where-Object { -not $_.IsCompatible }
    $unsupportedNotice = if ($incompatible) { "Detected unsupported Python: $($incompatible[0].Version)" } elseif ($globalVerStr -ne "None") { "Detected unsupported global Python: $globalVerStr" } else { "No Python runtime found" }

    Write-Host " [WARN] $unsupportedNotice (Project requires Python 3.10-3.12)." -ForegroundColor Yellow
    Write-Log "No compatible Python 3.10-3.12 found. $unsupportedNotice."

    # Attempt automatic self-healing side-by-side install of Python 3.11
    $installAttempted = Install-Python311SideBySide

    # Re-discover Python runtimes after install attempt
    $discovered = Discover-PythonInterpreters
    $compatible = $discovered | Where-Object { $_.IsCompatible } | Sort-Object Priority
}

if (-not $compatible) {
    Show-FailCard "Python Runtime" "A compatible Python runtime (3.10-3.12) is required, but none was detected or automatically installed. (Global runtime: $globalVerStr)." "Download and install Python 3.11 from https://www.python.org/downloads/ and make sure to check 'Add Python to PATH'." "SETUP-PYTHON-001"
    exit 1
}

# Select the highest-priority compatible Python interpreter (3.11 > 3.12 > 3.10)
$selectedPython = $compatible[0]
$selectedPythonPath = $selectedPython.Path
$selectedPyVersion = $selectedPython.Version

if ($globalVerStr -ne "None" -and $globalVerStr -notmatch "^3\.(10|11|12)\.") {
    Write-Host " [PASS] Python Runtime         : Selected Python $selectedPyVersion (Global: $globalVerStr preserved)" -ForegroundColor Green
    Write-Log "Selected compatible interpreter: $selectedPyVersion ($selectedPythonPath). Global Python ($globalVerStr) preserved safely."
} else {
    Write-Host " [PASS] Python Runtime         : Selected Python $selectedPyVersion ($selectedPythonPath)" -ForegroundColor Green
    Write-Log "Selected compatible interpreter: $selectedPyVersion ($selectedPythonPath) via $($selectedPython.Source)"
}

# =====================================================================
# STEP 2 — VIRTUAL ENVIRONMENT (.venv) VALIDATION & SELF-HEALING
# =====================================================================
Write-Host " -> Verifying project virtual environment (.venv)..." -ForegroundColor Gray

$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$reusedVenv = $false

if (Test-Path $VenvPython) {
    try {
        $venvVerOut = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $venvVerOut) {
            $venvVerStr = $venvVerOut.Trim()
            $parts = $venvVerStr.Split(".")
            $vMaj = [int]$parts[0]
            $vMin = [int]$parts[1]

            # Verify that the existing .venv was built with a compatible Python (3.10-3.12)
            if ($vMaj -eq 3 -and ($vMin -ge 10 -and $vMin -le 12)) {
                $reusedVenv = $true
                Write-Host " [PASS] Virtual Environment    : Reusing valid .venv (Python $venvVerStr)" -ForegroundColor Green
                Write-Log "Reused existing compatible virtual environment at $VenvDir (Python $venvVerStr)"
            } else {
                Write-Host " [WARN] Virtual Environment    : Existing .venv was created with unsupported Python $venvVerStr." -ForegroundColor Yellow
                Write-Host " -> Recreating .venv using compatible Python $selectedPyVersion..." -ForegroundColor Yellow
                Write-Log "Existing .venv had unsupported Python $venvVerStr. Removing and recreating."
                Remove-Item -Path $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 500
            }
        }
    } catch {
        Remove-Item -Path $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not $reusedVenv) {
    Write-Host " -> Creating virtual environment at .venv using Python $selectedPyVersion..." -ForegroundColor Gray
    try {
        & "$selectedPythonPath" -m venv "$VenvDir" 2>> $LogFile

        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
            throw "Virtual environment creation failed (exit code: $LASTEXITCODE)."
        }

        # Validate created .venv interpreter
        $newVenvVer = (& $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null).Trim()
        Write-Host " [PASS] Virtual Environment    : Created new .venv (Python $newVenvVer)" -ForegroundColor Green
        Write-Log "Created new virtual environment at $VenvDir using $selectedPythonPath (Python $newVenvVer)"
    } catch {
        Show-FailCard "Virtual Environment" "Failed to create Python virtual environment at $VenvDir using $selectedPythonPath." "Ensure write permissions in the project folder and that Python venv module is available." "SETUP-VENV-001"
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
        # Extract meaningful error lines from pip output
        $pipErrorLines = @($pipOut | Where-Object { $_ -match "ERROR:|failed with exit code|Could not find a version|No matching distribution" })
        if (-not $pipErrorLines -or $pipErrorLines.Count -eq 0) {
            $pipErrorLines = @($pipOut | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 6)
        }
        $pipErrorSummary = $pipErrorLines -join "`n "
        throw "Pip installation failed.`n $pipErrorSummary"
    }

    Write-Host " [PASS] Python Dependencies    : All requirements satisfied" -ForegroundColor Green
    Write-Log "Dependencies successfully installed from $ReqFile"
} catch {
    $errDetail = $_.Exception.Message
    Write-Host ""
    Write-Host " Pip Error Output:" -ForegroundColor Red
    Write-Host " $errDetail" -ForegroundColor Yellow
    Write-Host ""
    Show-FailCard "Dependencies" "Failed to install Python packages from requirements.txt.`n$errDetail" "Check your internet connection and verify that antivirus or corporate proxy is not blocking pip downloads." "SETUP-DEP-001"
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
# STEP 6 — CHECK FFMPEG ENGINE & AUTOMATED LOCAL ACQUISITION
# =====================================================================
Write-Host " -> Checking FFmpeg audio extraction engine..." -ForegroundColor Gray

$ffmpegFound = $false
$ffmpegPath = $null

# 1. Check project-local bin/ffmpeg.exe
$localFfmpeg = Join-Path $ProjectRoot "bin\ffmpeg.exe"
if (Test-Path $localFfmpeg) {
    try {
        $ffVer = & $localFfmpeg -version 2>$null
        if ($LASTEXITCODE -eq 0 -and $ffVer) {
            $ffmpegFound = $true
            $ffmpegPath = $localFfmpeg
        }
    } catch {}
}

# 2. Check system PATH
if (-not $ffmpegFound) {
    try {
        $sysFfmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
        if ($sysFfmpeg) {
            $ffVer = & $sysFfmpeg -version 2>$null
            if ($LASTEXITCODE -eq 0 -and $ffVer) {
                $ffmpegFound = $true
                $ffmpegPath = $sysFfmpeg
            }
        }
    } catch {}
}

# 3. Check FFMPEG_PATH environment variable
if (-not $ffmpegFound -and $env:FFMPEG_PATH -and (Test-Path $env:FFMPEG_PATH)) {
    try {
        $ffVer = & $env:FFMPEG_PATH -version 2>$null
        if ($LASTEXITCODE -eq 0 -and $ffVer) {
            $ffmpegFound = $true
            $ffmpegPath = $env:FFMPEG_PATH
        }
    } catch {}
}

# 4. Check local Windows build fallback
if (-not $ffmpegFound) {
    $winFallback = "C:\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
    if (Test-Path $winFallback) {
        $ffmpegFound = $true
        $ffmpegPath = $winFallback
    }
}

# 5. Automated local download if missing
if (-not $ffmpegFound) {
    Write-Host " -> FFmpeg not detected. Attempting automated local download to bin\ffmpeg.exe..." -ForegroundColor Gray
    Write-Log "FFmpeg not detected. Attempting automated download."

    $binDir = Join-Path $ProjectRoot "bin"
    if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir -Force | Out-Null }

    $tempZip = Join-Path $env:TEMP "ffmpeg_setup_download.zip"
    $sources = @(
        "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffmpeg-6.1-win-64.zip",
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    )

    foreach ($sourceUrl in $sources) {
        try {
            Write-Host " -> Downloading FFmpeg binary from $sourceUrl..." -ForegroundColor Gray
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $sourceUrl -OutFile $tempZip -TimeoutSec 90 -UseBasicParsing -ErrorAction Stop

            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $zip = [System.IO.Compression.ZipFile]::OpenRead($tempZip)
            $ffmpegEntry = $zip.Entries | Where-Object { $_.Name -ieq "ffmpeg.exe" } | Select-Object -First 1
            if ($ffmpegEntry) {
                $targetExe = Join-Path $binDir "ffmpeg.exe"
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($ffmpegEntry, $targetExe, $true)
                $zip.Dispose()

                $testVer = & $targetExe -version 2>$null
                if ($LASTEXITCODE -eq 0 -and $testVer) {
                    $ffmpegFound = $true
                    $ffmpegPath = $targetExe
                    Write-Log "FFmpeg automatically acquired and verified from $sourceUrl at $targetExe"
                    break
                }
            } else {
                $zip.Dispose()
            }
        } catch {
            Write-Log "FFmpeg automated acquisition from $sourceUrl failed: $($_.Exception.Message)"
        } finally {
            if (Test-Path $tempZip) { Remove-Item -Path $tempZip -Force -ErrorAction SilentlyContinue }
        }
    }
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
Write-Host " [PASS] Python Runtime         : Selected Python $selectedPyVersion" -ForegroundColor Green
Write-Host " [PASS] Virtual Environment    : Valid .venv" -ForegroundColor Green
Write-Host " [PASS] Dependencies           : All packages installed" -ForegroundColor Green
Write-Host " [PASS] Local Environment      : .env configured (2 GB limit)" -ForegroundColor Green
Write-Host " [PASS] Database / SQLite      : db.sqlite3 migrated" -ForegroundColor Green
Write-Host " [PASS] Required Directories   : media, staticfiles, bin ready" -ForegroundColor Green
Write-Host " [PASS] Django System Check    : 0 issues identified" -ForegroundColor Green
if ($ffmpegFound) {
    Write-Host " [PASS] FFmpeg Audio Engine    : Ready ($ffmpegPath)" -ForegroundColor Green
} else {
    Write-Host " [WARN] FFmpeg Audio Engine    : Missing (Action Required: place ffmpeg.exe in bin\)" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "----------------------------------------------------------------------" -ForegroundColor Cyan
Write-Host " Local upload limit : 2 GB" -ForegroundColor White
Write-Host " Database Engine    : SQLite (db.sqlite3)" -ForegroundColor White
Write-Host " Selected Python    : $selectedPyVersion" -ForegroundColor White
if ($globalVerStr -ne "None") {
    Write-Host " Global Python      : $globalVerStr" -ForegroundColor White
}
Write-Host " Application State  : Ready" -ForegroundColor White
Write-Host "----------------------------------------------------------------------" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next step:" -ForegroundColor Yellow
Write-Host "Double-click `"Verify Installation.bat`"" -ForegroundColor White
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green

Write-Log "Setup script finished successfully with exit code 0"
exit 0
