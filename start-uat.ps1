param(
    [string]$PythonPath = "",
    [int]$Port = 8765,
    [switch]$Lan
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$uatRuntimeConfig = Join-Path $PSScriptRoot ".runtime\python-path.txt"
if (-not $PythonPath -and (Test-Path -LiteralPath $uatRuntimeConfig)) {
    $PythonPath = (Get-Content -LiteralPath $uatRuntimeConfig -Raw).Trim()
}
if (-not $PythonPath) { $PythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python環境がありません。docs/INTEGRATED_UAT.md の初回準備を行うか、-PythonPath に既存のPythonを指定してください。"
}
& $PythonPath -c "import pandas, numpy.random, streamlit, uvicorn, websockets"
if ($LASTEXITCODE -ne 0) { throw "Pythonの計算ライブラリを読み込めません。docs/INTEGRATED_UAT.md の実行環境の項目を確認してください。" }
$uatArguments = @("uat_server.py", "--port", "$Port")
if ($Lan) { $uatArguments += "--lan" }
& $PythonPath @uatArguments
exit $LASTEXITCODE
