# Logs CPU time used by GD-bot work once a minute to build/power/samples.csv (gitignored).
#   gd_cpu_s    : GeometryDash.exe processes running from this repo's game\ folder (the frozen bot copy)
#   train_cpu_s : python processes whose command line points into this repo (training, tests, tools)
# Energy is estimated later by tools/dashboard/collect.py (CPU-seconds x per-thread package power).
# The user's own Steam GD (another folder) is never counted.
param([string]$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path, [int]$IntervalSec = 60)
$out = Join-Path $Repo "build\power\samples.csv"
New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
if (-not (Test-Path $out)) { "utc,interval_s,gd_cpu_s,train_cpu_s,gd_procs,train_procs" | Out-File -Encoding utf8 $out }
$gameDir = (Join-Path $Repo "game").ToLower()
$repoLow = $Repo.ToLower()
$last = @{}   # pid -> TotalProcessorTime seconds at previous sample
$prevT = Get-Date
while ($true) {
    Start-Sleep -Seconds $IntervalSec
    $now = Get-Date
    $gd = 0.0; $tr = 0.0; $ng = 0; $nt = 0
    $seen = @{}
    foreach ($p in Get-CimInstance Win32_Process -Filter "Name='GeometryDash.exe' OR Name='python.exe' OR Name='pythonw.exe'") {
        $path = "$($p.ExecutablePath)".ToLower(); $cmd = "$($p.CommandLine)".ToLower()
        $kind = $null
        if ($p.Name -eq 'GeometryDash.exe' -and $path.StartsWith($gameDir)) { $kind = 'gd' }
        elseif ($p.Name -ne 'GeometryDash.exe' -and ($cmd.Contains($repoLow) -or $cmd -match 'tools[\\/]m\d|gdbot|pytest')) { $kind = 'train' }
        if (-not $kind) { continue }
        $proc = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        $cpu = $proc.TotalProcessorTime.TotalSeconds
        $prev = if ($last.ContainsKey($p.ProcessId)) { $last[$p.ProcessId] } else { $cpu }   # first sight: count from now
        $d = [math]::Max(0, $cpu - $prev)
        $last[$p.ProcessId] = $cpu; $seen[$p.ProcessId] = $true
        if ($kind -eq 'gd') { $gd += $d; $ng++ } else { $tr += $d; $nt++ }
    }
    foreach ($k in @($last.Keys)) { if (-not $seen.ContainsKey($k)) { $last.Remove($k) } }
    $iv = [math]::Round(($now - $prevT).TotalSeconds, 1); $prevT = $now
    "{0},{1},{2:F2},{3:F2},{4},{5}" -f $now.ToUniversalTime().ToString("s"), $iv, $gd, $tr, $ng, $nt | Out-File -Append -Encoding utf8 $out
}
