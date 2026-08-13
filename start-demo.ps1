$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$bundledPython = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$bundledPnpm = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd'
$venvPython = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
  Write-Host 'Creating local Python environment...'
  & $bundledPython -m venv (Join-Path $root '.venv')
}

Write-Host 'Checking backend dependencies...'
& $venvPython -m pip install -q -r (Join-Path $root 'backend\requirements.txt')

if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\node_modules'))) {
  Write-Host 'Installing frontend dependencies...'
  & $bundledPnpm --dir (Join-Path $root 'frontend') install
}

$backend = Start-Process -FilePath $venvPython -WorkingDirectory $root -WindowStyle Hidden -PassThru -ArgumentList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000')
$frontend = Start-Process -FilePath $bundledPnpm -WorkingDirectory $root -WindowStyle Hidden -PassThru -ArgumentList @('--dir', (Join-Path $root 'frontend'), 'dev', '--host', '127.0.0.1', '--port', '5173')

Write-Host ''
Write-Host 'Monitoring Mentor Demo started.'
Write-Host 'Open: http://127.0.0.1:5173'
Write-Host "Backend PID: $($backend.Id); Frontend PID: $($frontend.Id)"
