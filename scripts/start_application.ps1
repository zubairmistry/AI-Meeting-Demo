<#
.SYNOPSIS
    AI Meeting Assistant - Windows Application Launcher Script
.DESCRIPTION
    Performs quick safe pre-flight checks, discovers an available local port (default 8000),
    starts the Django development server on 127.0.0.1, automatically opens the default browser,
    and manages the server lifecycle until closed by the user (CTRL+C).
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# ----------------------------------------------------------------------
# 0. DYNAMICALLY DETERMINE PROJECT ROOT
# ----------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path "$ScriptDir\..").Path

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
    Write-Host ""
}

# ----------------------------------------------------------------------
# STEP 1 — PRE-FLIGHT CHECKS
# ----------------------------------------------------------------------
Write-Host " -> Checking application readiness..." -ForegroundColor Gray

$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ManagePy = Join-Path $ProjectRoot "manage.py"
$DbFile = Join-Path $ProjectRoot "db.sqlite3"
$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $VenvPython)) {
    Show-FailCard "Application Virtual Environment" "The Python virtual environment (.venv) was not found." "Run 'Setup Application.bat' and then 'Verify Installation.bat'." "START-VENV-001"
    exit 1
}

if (-not (Test-Path $ManagePy)) {
    Show-FailCard "Application Files" "manage.py was not found in the project root." "Re-extract the application package or contact IT support." "START-FILE-001"
    exit 1
}

if (-not (Test-Path $EnvFile)) {
    Show-FailCard "Configuration" ".env configuration file was not found." "Run 'Setup Application.bat' to generate local configuration." "START-ENV-001"
    exit 1
}

if (-not (Test-Path $DbFile)) {
    Show-FailCard "Database Engine" "db.sqlite3 database was not found." "Run 'Setup Application.bat' to initialize the local SQLite database." "START-DB-001"
    exit 1
}

# ----------------------------------------------------------------------
# STEP 2 — PORT DISCOVERY & DUPLICATE INSTANCE DETECTION
# ----------------------------------------------------------------------
function Test-PortAvailable {
    param([int]$Port)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Test-IsAiMeetingServer {
    param([int]$Port)
    try {
        $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/")
        $req.Timeout = 1500
        $req.AllowAutoRedirect = $true
        $resp = $req.GetResponse()
        $stream = $resp.GetResponseStream()
        $reader = [System.IO.StreamReader]::new($stream)
        $content = $reader.ReadToEnd()
        $resp.Close()
        if ($content -match "AI Meeting" -or $content -match "Meeting Minutes" -or $content -match "ai_meeting" -or $content -match "csrfmiddlewaretoken") {
            return $true
        }
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) {
            try {
                $respStream = $_.Exception.Response.GetResponseStream()
                $respReader = [System.IO.StreamReader]::new($respStream)
                $respContent = $respReader.ReadToEnd()
                $_.Exception.Response.Close()
                if ($respContent -match "AI Meeting" -or $respContent -match "Meeting Minutes" -or $respContent -match "ai_meeting" -or $respContent -match "csrfmiddlewaretoken") {
                    return $true
                }
            } catch {}
        }
    } catch {}
    return $false
}

$selectedPort = $null

# First check if port 8000 is free or already running this app
if (Test-PortAvailable 8000) {
    $selectedPort = 8000
} elseif (Test-IsAiMeetingServer 8000) {
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host " AI MEETING ASSISTANT IS ALREADY RUNNING" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host " URL:" -ForegroundColor Yellow
    Write-Host " http://127.0.0.1:8000/" -ForegroundColor White
    Write-Host ""
    Write-Host " The application is already active on port 8000." -ForegroundColor White
    Write-Host " Opening your browser now..." -ForegroundColor Cyan
    Write-Host "======================================================================" -ForegroundColor Green
    Start-Process "http://127.0.0.1:8000/"
    exit 0
} else {
    Write-Host " -> Port 8000 is occupied by another application. Searching ports 8001-8010..." -ForegroundColor Yellow
    for ($p = 8001; $p -le 8010; $p++) {
        if (Test-IsAiMeetingServer $p) {
            Write-Host ""
            Write-Host "======================================================================" -ForegroundColor Green
            Write-Host " AI MEETING ASSISTANT IS ALREADY RUNNING" -ForegroundColor Green
            Write-Host "======================================================================" -ForegroundColor Green
            Write-Host ""
            Write-Host " URL:" -ForegroundColor Yellow
            Write-Host " http://127.0.0.1:$p/" -ForegroundColor White
            Write-Host ""
            Write-Host " The application is already active on port $p." -ForegroundColor White
            Write-Host " Opening your browser now..." -ForegroundColor Cyan
            Write-Host "======================================================================" -ForegroundColor Green
            Start-Process "http://127.0.0.1:$p/"
            exit 0
        } elseif (Test-PortAvailable $p) {
            $selectedPort = $p
            break
        }
    }
}

if (-not $selectedPort) {
    Show-FailCard "Application Port" "No available local port was found between 8000 and 8010." "Close an unused local application or contact IT support." "START-PORT-001"
    exit 1
}

# ----------------------------------------------------------------------
# STEP 3 — START DJANGO SERVER
# ----------------------------------------------------------------------
Write-Host " -> Starting application server on 127.0.0.1:$selectedPort..." -ForegroundColor Gray

$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $VenvPython
$psi.Arguments = "`"$ManagePy`" runserver 127.0.0.1:$selectedPort"
$psi.WorkingDirectory = $ProjectRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $false

$djangoProcess = [System.Diagnostics.Process]::Start($psi)
if (-not $djangoProcess) {
    Show-FailCard "Application Startup" "Failed to spawn Django application process." "Run 'Verify Installation.bat' and review verify_report.txt." "START-DJANGO-001"
    exit 1
}

# ----------------------------------------------------------------------
# STEP 4 — POLL READINESS & LAUNCH BROWSER
# ----------------------------------------------------------------------
$isReady = $false
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$appUrl = "http://127.0.0.1:$selectedPort/"

while ($sw.ElapsedMilliseconds -lt 15000) {
    if ($djangoProcess.HasExited) {
        break
    }
    try {
        $req = [System.Net.HttpWebRequest]::Create($appUrl)
        $req.Timeout = 1000
        $req.AllowAutoRedirect = $false
        $resp = $req.GetResponse()
        $code = [int]$resp.StatusCode
        $resp.Close()
        if ($code -ge 200 -and $code -lt 500) {
            $isReady = $true
            break
        }
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
            $_.Exception.Response.Close()
            if ($code -ge 200 -and $code -lt 500) {
                $isReady = $true
                break
            }
        }
    } catch {}
    Start-Sleep -Milliseconds 300
}

if (-not $isReady) {
    if ($djangoProcess.HasExited) {
        Show-FailCard "Application Startup" "The application process exited unexpectedly during startup." "Run 'Verify Installation.bat' and review verify_report.txt." "START-DJANGO-001"
    } else {
        try { $djangoProcess.Kill() } catch {}
        Show-FailCard "Application Startup" "The application server did not respond within 15 seconds." "Run 'Verify Installation.bat' and review verify_report.txt." "START-DJANGO-002"
    }
    exit 1
}

# Automatically open default browser
Start-Process $appUrl

# ----------------------------------------------------------------------
# STEP 5 — RUNNING SCREEN & LIFECYCLE MANAGEMENT
# ----------------------------------------------------------------------
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host " AI MEETING ASSISTANT IS RUNNING" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
Write-Host " URL:" -ForegroundColor Yellow
Write-Host " $appUrl" -ForegroundColor White
Write-Host ""
Write-Host " Status:" -ForegroundColor Yellow
Write-Host " RUNNING" -ForegroundColor Green
Write-Host ""
Write-Host " The application is running locally on this computer." -ForegroundColor White
Write-Host ""
Write-Host " Keep this window open while using the application." -ForegroundColor Gray
Write-Host ""
Write-Host " To stop the application:" -ForegroundColor Yellow
Write-Host " Press CTRL+C" -ForegroundColor White
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green

# Wait for process exit or user interruption
try {
    $djangoProcess.WaitForExit()
} finally {
    if (-not $djangoProcess.HasExited) {
        try {
            $djangoProcess.Kill()
        } catch {}
    }
}

