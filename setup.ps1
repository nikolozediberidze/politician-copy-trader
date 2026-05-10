# One-time setup: create venv and install dependencies
$dir = $PSScriptRoot

Write-Host "Creating virtual environment..." -ForegroundColor Cyan
python -m venv "$dir\.venv"

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& "$dir\.venv\Scripts\pip.exe" install -r "$dir\requirements.txt" --upgrade

Write-Host ""
Write-Host "Setup complete. Run 'run.ps1' to start the bot." -ForegroundColor Green
