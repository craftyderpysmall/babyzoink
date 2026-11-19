# Run by Windows Task Scheduler ("babyzoink dashboard data", daily 20:03 local).
# 1) makes sure the power sampler is running, 2) runs both collectors, 3) force-pushes the data
# files as a single commit to the `dashboard-data` branch using git plumbing (the working tree and
# the current branch are never touched, so it is safe while Codex or Claude are editing).
# A cloud routine (~20:20) then reads that branch and updates the dashboard artifact.
$ErrorActionPreference = "Stop"
$OutputEncoding = New-Object System.Text.UTF8Encoding $false   # no BOM when piping into git mktree
$repo = "C:\Users\user\Documents\babyzoink"
Set-Location $repo
$logDir = Join-Path $repo "build\dashboard\refresh-logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("refresh-{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))
function Log($m) { "[{0}] {1}" -f (Get-Date -Format s), $m | Out-File -Append -Encoding utf8 $log }
try {
    $sampler = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like "*power_sampler.ps1*" }
    if (-not $sampler) {
        Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$repo\tools\dashboard\power_sampler.ps1"
        Log "power sampler was not running; started it"
    }
    $out = & python -I tools\dashboard\collect.py 2>&1
    Log "collect: $out"
    # New ChatGPT Sites dashboard: one combined snapshot (incl. per-mode ratings from build\telemetry).
    # The site reads it from the public dashboard-data branch at view time (site/DEPLOY.md).
    $out = & "$repo\build\gdbot-venv\Scripts\python.exe" tools\site\export.py --refresh-gddl --output build\dashboard\site-dashboard.json 2>&1
    if ($LASTEXITCODE -ne 0) { throw "site export failed: $out" }
    Log "site export: $out"
    $files = "energy_daily.json", "milestones.json", "results.json", "price.json", "site-dashboard.json"
    $lines = foreach ($f in $files) {
        $sha = (& git hash-object -w "build\dashboard\$f").Trim()
        "100644 blob $sha`t$f"
    }
    $spec = Join-Path $logDir "tree.txt"
    [System.IO.File]::WriteAllText($spec, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
    $tree = (& cmd /c "git mktree < `"$spec`"").Trim()
    $commit = (& git commit-tree $tree -m ("dashboard data {0:yyyy-MM-dd HH:mm}" -f (Get-Date))).Trim()
    $ErrorActionPreference = "Continue"   # git prints normal progress to stderr; judge by exit code
    $push = & git push -f origin "${commit}:refs/heads/dashboard-data" 2>&1 | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($code -ne 0) { throw "git push exit $code : $push" }
    Log "pushed $commit to dashboard-data"
} catch {
    Log "FAILED: $($_.Exception.Message)"
    exit 1
}
