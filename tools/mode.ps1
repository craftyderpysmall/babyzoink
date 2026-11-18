# Switch the GD bot between running flat out and running politely in the background.
#   tools\mode.ps1 dedicated    use all CPU threads, as fast as possible
#   tools\mode.ps1 background   below-normal priority, 4 threads; your own apps always come first
#   tools\mode.ps1 auto         let the training script decide again
#   tools\mode.ps1              show the current setting
# Same as pressing Ctrl+Alt+B (toggles dedicated/background) while the bot's game is running.
# The bridge picks the change up within about a second; the choice persists across trainer restarts.
param([ValidateSet("dedicated", "background", "auto", "status")] [string]$Mode = "status")
$file = Join-Path $PSScriptRoot "..\game\2.2091\gdbot\mode.txt"
$log = Join-Path $PSScriptRoot "..\game\2.2091\gdbot\bridge.log"
if ($Mode -eq "status") {
    $set = if (Test-Path $file) { (Get-Content $file -Raw).Trim() } else { "auto (no user choice)" }
    "Your setting: $set"
    if (Test-Path $log) {
        $last = Select-String -Path $log -Pattern "mode -> " | Select-Object -Last 1
        if ($last) { "Bridge last applied: " + ($last.Line -replace '^.*mode -> ', '') }
    }
    return
}
[System.IO.File]::WriteAllText($file, $Mode)
"Set to $Mode. The running game applies it within about a second."
