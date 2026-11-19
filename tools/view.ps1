# Watch a bot slot at 1x and show/hide the on-screen overlay without the hotkeys
# (use it if Ctrl+Alt+V / Ctrl+Alt+O are taken by another app).
#   tools\view.ps1 watch 2       watch slot 2 at real-time speed (1x)
#   tools\view.ps1 unwatch       back to full speed
#   tools\view.ps1 overlay on    show the overlay on every slot (off to hide)
#   tools\view.ps1               show the current setting
# Same as Ctrl+Alt+V / Ctrl+Alt+O. Every running slot picks the change up within about a quarter second.
param([ValidateSet("watch", "unwatch", "overlay", "status")] [string]$Action = "status", [string]$Value = "")
$file = Join-Path $PSScriptRoot "..\game\2.2091\gdbot\view.json"
$view = @{ overlay = $true; watch_slot = $null }
if (Test-Path $file) {
    try { $j = Get-Content $file -Raw | ConvertFrom-Json; $view.overlay = [bool]$j.overlay; $view.watch_slot = $j.watch_slot } catch {}
}
switch ($Action) {
    "status" {
        $w = if ($null -eq $view.watch_slot) { "nothing (all slots at full speed)" } else { "slot $($view.watch_slot) at 1x" }
        "Overlay: $(if ($view.overlay) { 'shown' } else { 'hidden' })    Watching: $w"
        return
    }
    "watch" {
        if ($Value -notmatch '^\d+$') { "Usage: tools\view.ps1 watch <slot number>"; return }
        $view.watch_slot = [int]$Value
    }
    "unwatch" { $view.watch_slot = $null }
    "overlay" {
        if ($Value -notin @("on", "off")) { "Usage: tools\view.ps1 overlay on|off"; return }
        $view.overlay = $Value -eq "on"
    }
}
$tmp = "$file.tmp.ps"
[System.IO.File]::WriteAllText($tmp, ($view | ConvertTo-Json -Compress))
Move-Item -Force $tmp $file
"Done. Overlay: $(if ($view.overlay) { 'shown' } else { 'hidden' })    Watching: $(if ($null -eq $view.watch_slot) { 'nothing' } else { 'slot ' + $view.watch_slot })"
