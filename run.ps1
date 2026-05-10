# Run the copy trading bot (single check — called by Task Scheduler every 30 min)
$dir = $PSScriptRoot
$python = "$dir\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Virtual environment not found. Run setup.ps1 first." -ForegroundColor Red
    exit 1
}

Set-Location $dir
& $python bot.py
