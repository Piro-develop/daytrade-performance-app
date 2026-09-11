param([switch]$Execute)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$releaseGit = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $releaseGit) { $releaseGit = "C:\Program Files\Git\cmd\git.exe" }
function Invoke-ReleaseGit {
    $releaseOutput = & $releaseGit @args
    if ($LASTEXITCODE -ne 0) { throw "Git command failed. No further action was taken." }
    return $releaseOutput
}
$releaseBaseline = Get-Content -LiteralPath "deploy/production-baseline.json" -Raw | ConvertFrom-Json
$releaseTarget = $releaseBaseline.remote_main
$releaseTagTarget = (Invoke-ReleaseGit rev-parse "$($releaseBaseline.rollback_tag)^{commit}").Trim()
if ($releaseTagTarget -ne $releaseTarget) { throw "Rollback tag differs from the recorded production baseline." }
Write-Output "Rollback target: $releaseTarget"
Write-Output "This restores committed application files only. Firebase and analysis databases are not modified."
if (-not $Execute) {
    Write-Output "Preview only. To restore after release: .\scripts\rollback-production.ps1 -Execute"
    exit 0
}
if (Invoke-ReleaseGit status --porcelain) { throw "Uncommitted changes exist. Preserve them before rollback." }
$releaseBranch = (Invoke-ReleaseGit branch --show-current).Trim()
if ($releaseBranch -ne "main") { throw "Run rollback on main." }
$releaseOrigin = (Invoke-ReleaseGit remote get-url origin).Trim().TrimEnd("/")
if ($releaseOrigin -notmatch '^https://github\.com/[Pp]iro-develop/daytrade-performance-app(\.git)?$') { throw "Unexpected origin." }
$releaseHead = (Invoke-ReleaseGit rev-parse HEAD).Trim()
$releaseRemote = ((Invoke-ReleaseGit ls-remote origin refs/heads/main) -split "\s+")[0]
if ($releaseHead -ne $releaseRemote) { throw "Local main differs from remote main. Inspect before rollback." }
Invoke-ReleaseGit merge-base --is-ancestor $releaseTarget HEAD
# Git restore never deletes untracked personal data. No reset --hard, clean, or force-push.
Invoke-ReleaseGit restore "--source=$releaseTarget" --staged --worktree -- .
if (-not (Invoke-ReleaseGit diff --cached --name-only)) { Write-Output "Already at baseline."; exit 0 }
Invoke-ReleaseGit diff --cached --check
Invoke-ReleaseGit commit -m "Restore production baseline before stock judgment"
Invoke-ReleaseGit push origin HEAD:refs/heads/main
Write-Output "Rollback pushed. Verify the Pages build and public URL before concluding."
