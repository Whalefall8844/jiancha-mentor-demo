$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm -ErrorAction SilentlyContinue

if (-not $pythonCommand) {
  throw '未找到 Python。请先安装 Python 3.10 或更高版本，并在安装时勾选 Add Python to PATH。'
}

if (-not $npmCommand) {
  throw '未找到 Node.js / npm。请先安装 Node.js 20 LTS 或更高版本。'
}

$python = $pythonCommand.Source
$npm = $npmCommand.Source
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$frontendRoot = Join-Path $root 'frontend'

if (-not (Test-Path -LiteralPath $venvPython)) {
  Write-Host '正在创建本地 Python 环境...'
  & $python -m venv (Join-Path $root '.venv')
}

Write-Host '正在安装后端依赖...'
& $venvPython -m pip install -q -r (Join-Path $root 'backend\requirements.txt')

if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules'))) {
  Write-Host '正在安装前端依赖...'
  & $npm --prefix $frontendRoot install
}

$backend = Start-Process -FilePath $venvPython -WorkingDirectory $root -WindowStyle Hidden -PassThru -ArgumentList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000')
$frontend = Start-Process -FilePath $npm -WorkingDirectory $root -WindowStyle Hidden -PassThru -ArgumentList @('--prefix', $frontendRoot, 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173')

Write-Host ''
Write-Host '监查 Mentor Demo 已启动。'
Write-Host '打开: http://127.0.0.1:5173'
Write-Host "后端 PID: $($backend.Id); 前端 PID: $($frontend.Id)"
