param(
    [string]$PythonPath = "",
    [int]$Port = 8766,
    [string]$BindAddress = "127.0.0.1",
    [string]$DataDirectory = ""
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$judgmentRuntimeConfig = Join-Path $PSScriptRoot ".runtime\\python-path.txt"
if (-not $PythonPath -and (Test-Path -LiteralPath $judgmentRuntimeConfig)) {
    $PythonPath = (Get-Content -LiteralPath $judgmentRuntimeConfig -Raw).Trim()
}
if (-not $PythonPath) { $PythonPath = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe" }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Python環境を準備し、-PythonPath で指定してください。docs/PRODUCTION_INTEGRATION.md を参照してください。" }
& $PythonPath -c "import pandas, numpy.random, PIL, uvicorn, starlette, requests"
if ($LASTEXITCODE -ne 0) { throw "計算ライブラリを読み込めません。Python環境を確認してください。" }
$judgmentArguments = @("app_server.py", "--port", "$Port", "--host", $BindAddress)
if ($DataDirectory) { $judgmentArguments += @("--data-dir", $DataDirectory) }
& $PythonPath @judgmentArguments
exit $LASTEXITCODE
