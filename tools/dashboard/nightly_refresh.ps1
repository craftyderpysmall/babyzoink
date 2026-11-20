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
$log = Join-Path $logDir ("refresh-{0:yyyy-MM-dd_HHmmss}-{1}.log" -f (Get-Date), $PID)
function Log($m) { "[{0}] {1}" -f (Get-Date -Format s), $m | Out-File -Append -Encoding utf8 $log }
function Git-Ok { param([string[]]$GitArgs)
    $ErrorActionPreference = "Continue"   # git prints normal progress to stderr; judge by exit code
    $out = & git @GitArgs 2>&1 | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    return @{ Code = $code; Out = $out.Trim() }
}
function Git-Checked { param([string[]]$GitArgs)
    $result = Git-Ok $GitArgs
    if ($result.Code -ne 0) { throw "git $($GitArgs[0]) failed: $($result.Out)" }
    return $result.Out
}
$index = Join-Path $logDir ("nightly-{0}.index" -f [guid]::NewGuid())
$previousIndex = [Environment]::GetEnvironmentVariable("GIT_INDEX_FILE", "Process")
$refreshLock = $null
try {
    # Collectors also share staging paths. Hold this file open exclusively through publication.
    $refreshLock = [IO.File]::Open((Join-Path $logDir "refresh.lock"), "OpenOrCreate", "ReadWrite", "None")
    $sampler = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like "*power_sampler.ps1*" }
    if (-not $sampler) {
        Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$repo\tools\dashboard\power_sampler.ps1"
        Log "power sampler was not running; started it"
    }
    $out = & "$repo\build\gdbot-venv\Scripts\python.exe" tools\site\backfill_attempts.py 2>&1   # per-level normal/practice attempts
    if ($LASTEXITCODE -ne 0) { throw "attempts ledger failed: $out" }
    Log "attempts ledger: $out"
    $out = & python -I tools\dashboard\collect.py 2>&1
    if ($LASTEXITCODE -ne 0) { throw "artifact collection failed: $out" }
    Log "collect: $out"
    $out = & "$repo\build\gdbot-venv\Scripts\python.exe" tools\site\export.py --refresh-gddl --output build\dashboard\site-dashboard.json 2>&1
    if ($LASTEXITCODE -ne 0) { throw "site export failed: $out" }
    Log "site export: $out"
    $files = "energy_daily.json", "milestones.json", "results.json", "price.json", "attempts.json", "site-dashboard.json"
    $allowedPaths = $files | ForEach-Object { "data/dashboard/$_" }
    for ($try = 1; $try -le 4; $try++) {
        Git-Checked @("fetch", "-q", "origin", "main") | Out-Null
        $base = Git-Checked @("rev-parse", "origin/main")
        $env:GIT_INDEX_FILE = $index
        Git-Checked @("read-tree", $base) | Out-Null
        foreach ($f in $files) {
            $sha = Git-Checked @("hash-object", "-w", "build\dashboard\$f")
            Git-Checked @("update-index", "--add", "--cacheinfo", "100644,$sha,data/dashboard/$f") | Out-Null
        }
        $tree = Git-Checked @("write-tree")
        [Environment]::SetEnvironmentVariable("GIT_INDEX_FILE", $previousIndex, "Process")
        $baseTree = Git-Checked @("rev-parse", "$base^{tree}")
        if ($tree -eq $baseTree) { Log "data unchanged; nothing to push"; break }
        $paths = (Git-Checked @("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", $baseTree, $tree)) -split '\r?\n'
        $unexpected = $paths | Where-Object { $_ -and $_ -cnotin $allowedPaths }
        if ($unexpected) { throw "unexpected paths in dashboard commit: $($unexpected -join ', ')" }
        $commit = Git-Checked @("commit-tree", $tree, "-p", $base, "-m", ("Nightly dashboard data {0:yyyy-MM-dd HH:mm}" -f (Get-Date)))
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
    [Environment]::SetEnvironmentVariable("GIT_INDEX_FILE", $previousIndex, "Process")
    if ($refreshLock) { $refreshLock.Dispose() }
    if (Test-Path -LiteralPath $index) { Remove-Item -LiteralPath $index -Force }
}
