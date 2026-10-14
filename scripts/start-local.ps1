# Run from the project root after completing README setup.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'ai-service\.venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw 'Create ai-service/.venv and install requirements first.' }
$runner = Join-Path $PSScriptRoot 'run.py'
foreach ($service in @('identity','expense','policy','gateway','ai-api','ai-worker','frontend')) {
    # Arguments are passed as PowerShell literals; project paths may contain spaces.
    $pyLiteral = "'" + $python.Replace("'", "''") + "'"
    $runLiteral = "'" + $runner.Replace("'", "''") + "'"
    Start-Process powershell -WorkingDirectory $root -ArgumentList '-NoExit','-Command',"& $pyLiteral $runLiteral $service"
}
Write-Host 'Started local terminals. Open http://127.0.0.1:5173 after the services report ready.'
