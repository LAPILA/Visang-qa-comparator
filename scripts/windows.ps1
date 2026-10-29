param([switch]$Setup)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if ((Test-Path -LiteralPath $venvPython) -and -not $Setup) {
    & $venvPython app.py
    exit $LASTEXITCODE
}
$pythonCandidates = @()
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand -and $pythonCommand.Source -notlike '*\WindowsApps\*') {
    $pythonCandidates += $pythonCommand.Source
}
$pythonInstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
if (Test-Path -LiteralPath $pythonInstallRoot) {
    $pythonCandidates += Get-ChildItem -LiteralPath $pythonInstallRoot -Filter python.exe -Recurse |
        Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName
}
$selectedPython = $null
foreach ($candidate in $pythonCandidates) {
    & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
    if ($LASTEXITCODE -eq 0) { $selectedPython = $candidate; break }
}
if (-not $selectedPython) { throw 'Install Python 3.10+ first, then run setup_windows.bat.' }
if ($Setup) {
    & $selectedPython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $venvPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }
    Write-Host 'Setup complete. Run run_windows.bat.'
} else {
    & $selectedPython app.py
    exit $LASTEXITCODE
}
