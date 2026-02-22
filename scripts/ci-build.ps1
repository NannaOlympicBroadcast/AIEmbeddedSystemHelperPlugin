<#
.SYNOPSIS
    CI build script - install deps, build backend, compile extension, package VSIX
.USAGE
    .\scripts\ci-build.ps1              # full build
    .\scripts\ci-build.ps1 -SkipBackend # skip PyInstaller (faster)
    .\scripts\ci-build.ps1 -DevRun      # build then start backend
#>

param(
    [switch]$SkipBackend,
    [switch]$DevRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Backend = Join-Path $Root "backend"
$Extension = Join-Path $Root "extension"

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Test-ExitCode {
    param([string]$StepName)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $StepName (exit code $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "[OK] $StepName" -ForegroundColor Green
}

# 1. Python deps
Write-Step -Text "1/5  Installing Python dependencies"
$ErrorActionPreference = "Continue"
pip install -r (Join-Path $Backend "requirements.txt") --quiet 2>$null
$ErrorActionPreference = "Stop"
Test-ExitCode -StepName "pip install"

# 2. Python import test
Write-Step -Text "2/5  Verifying Python agent"
Push-Location $Backend
python -c "from embedded_system_helper import root_agent; print('Agent: ' + root_agent.name + '  Tools: ' + str(len(root_agent.tools)) + '  SubAgents: ' + str(len(root_agent.sub_agents)))"
Test-ExitCode -StepName "Python import test"
Pop-Location

# 3. PyInstaller
if (-not $SkipBackend) {
    Write-Step -Text "3/5  Building backend executable (PyInstaller)"
    python (Join-Path $Root "scripts\build_backend.py")
    Test-ExitCode -StepName "PyInstaller build"

    $exe = Join-Path $Extension "resources\bin\backend-win.exe"
    if (Test-Path $exe) {
        $sizeVal = [math]::Round((Get-Item $exe).Length / 1048576, 1)
        Write-Host "  -> $exe ($sizeVal megabytes)" -ForegroundColor DarkGray
    }
} else {
    Write-Step -Text "3/5  Skipping PyInstaller build (SkipBackend)"
}

# 4. Node deps + TypeScript
Write-Step -Text "4/5  Installing Node deps and compiling TypeScript"
Push-Location $Extension
npm install --silent 2>&1 | Out-Null
Test-ExitCode -StepName "npm install"
npx tsc -p .
Test-ExitCode -StepName "tsc compile"
Pop-Location

# 5. VSIX package
Write-Step -Text "5/5  Packaging VSIX"
Push-Location $Extension
npx vsce package --no-dependencies 2>&1
Test-ExitCode -StepName "vsce package"
$vsix = Get-ChildItem -Filter "*.vsix" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($vsix) {
    $sizeVal = [math]::Round($vsix.Length / 1048576, 1)
    Write-Host ""
    Write-Host "  [DONE] $($vsix.Name)  ($sizeVal megabytes)" -ForegroundColor Green
    Write-Host "  Install:  code --install-extension $($vsix.FullName)" -ForegroundColor DarkGray
}
Pop-Location

# DevRun mode: hot-reload enabled (code changes auto-restart backend)
if ($DevRun) {
    Write-Step -Text "DevRun - Starting backend server (hot-reload ON)"
    $env:DEV_RELOAD = "1"
    Push-Location $Backend
    python main.py
    Pop-Location
    $env:DEV_RELOAD = "0"
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
