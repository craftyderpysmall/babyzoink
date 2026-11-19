# Run by Windows Task Scheduler ("babyzoink dashboard data", daily 20:03 local).
# 1) makes sure the power sampler is running, 2) runs both collectors, 3) commits the data files to
# `main` under data/dashboard/ and pushes. Single-branch repo (user rule): no side branches.
# Git plumbing with a private index builds the commit on top of origin/main, so the working tree,
# the local index and whatever Codex or Claude are editing are never touched. On a push race it
# refetches and retries. Agents pull --rebase before their own pushes.
# Readers: the ChatGPT Site (site-dashboard.json, at view time) and the old artifact's cloud routine
# (~20:20, the four other *.json files) until cutover.
$ErrorActionPreference = "Stop"
$repo = "C:\Users\user\Documents\babyzoink"
Set-Location $repo
$logDir = Join-Path $repo "build\dashboard\refresh-logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("refresh-{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))
function Log($m) { "[{0}] {1}" -f (Get-Date -Format s), $m | Out-File -Append -Encoding utf8 $log }
function Git-Ok { param([string[]]$GitArgs)
    $ErrorActionPreference = "Continue"   # git prints normal progress to stderr; judge by exit code
    $out = & git @GitArgs 2>&1 | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    return @{ Code = $code; Out = $out.Trim() }
}
$index = Join-Path $logDir "nightly.index"
try {
    $sampler = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like "*power_sampler.ps1*" }
    if (-not $sampler) {
        Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$repo\tools\dashboard\power_sampler.ps1"
        Log "power sampler was not running; started it"
    }
    $out = & python -I tools\dashboard\collect.py 2>&1
    Log "collect: $out"
    $out = & "$repo\build\gdbot-venv\Scripts\python.exe" tools\site\backfill_attempts.py 2>&1   # per-level normal/practice attempts
    Log "attempts ledger: $out"
    $out = & "$repo\build\gdbot-venv\Scripts\python.exe" tools\site\export.py --refresh-gddl --output build\dashboard\site-dashboard.json 2>&1
    if ($LASTEXITCODE -ne 0) { throw "site export failed: $out" }
    Log "site export: $out"
    $files = "energy_daily.json", "milestones.json", "results.json", "price.json", "site-dashboard.json"
    for ($try = 1; $try -le 4; $try++) {
        $r = Git-Ok @("fetch", "-q", "origin", "main"); if ($r.Code -ne 0) { throw "fetch: $($r.Out)" }
        $base = (& git rev-parse origin/main).Trim()
        $env:GIT_INDEX_FILE = $index
        & git read-tree $base
        foreach ($f in $files) {
            $sha = (& git hash-object -w "build\dashboard\$f").Trim()
            & git update-index --add --cacheinfo "100644,$sha,data/dashboard/$f"
        }
        $tree = (& git write-tree).Trim()
        Remove-Item Env:GIT_INDEX_FILE
        if ($tree -eq (& git rev-parse "$base^{tree}").Trim()) { Log "data unchanged; nothing to push"; break }
        $commit = (& git commit-tree $tree -p $base -m ("Nightly dashboard data {0:yyyy-MM-dd HH:mm}" -f (Get-Date))).Trim()
        $r = Git-Ok @("push", "origin", "${commit}:refs/heads/main")
        if ($r.Code -eq 0) { Log "pushed $commit to main (data/dashboard/)"; break }
        Log "push attempt $try rejected (main moved?): $($r.Out)"
        if ($try -eq 4) { throw "push failed 4 times" }
        Start-Sleep -Seconds (5 * $try)
    }
} catch {
    Log "FAILED: $($_.Exception.Message)"
    exit 1
} finally {
    if (Test-Path Env:GIT_INDEX_FILE) { Remove-Item Env:GIT_INDEX_FILE }
    if (Test-Path $index) { Remove-Item $index -Force }
}
