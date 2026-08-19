<#
laptop_allow_patrimonio_on_battery.ps1 -- roadmap R23, the half that needed a decision.

RUN THIS ON THE LAPTOP:
  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_allow_patrimonio_on_battery.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_allow_patrimonio_on_battery.ps1

WHAT. Sets <DisallowStartIfOnBatteries>false</> on `\BD\Finance\Patrimonio Monthly`, so the
day-27 09:00 start -- and any catch-up for it -- is no longer refused because the laptop is
unplugged. Decided 2026-08-19: allow the START on battery, KEEP the stop.

WHY THIS AND NOT BOTH. <StopIfGoingOnBatteries> stays TRUE on purpose. This chain writes
`Patrimonio BD.xlsx` through Excel COM on a copy with a timestamped backup, and a write killed
half-way is worse than a run that never happened. The two settings look symmetric and are not:
one decides whether work begins, the other can interrupt work already in flight.

WHY IT WAS NEEDED. laptop_fix_patrimonio_catchup.ps1 turned StartWhenAvailable on, but a
catch-up is still a start, and a start on battery was refused -- so the fix could have looked
applied and produced no run at all. 09:00 on a workday is exactly when a laptop is unplugged.

WHY XML AND NOT Set-ScheduledTask. MONTHLY task. Get-ScheduledTask returns its CalendarTrigger
as the base MSFT_TaskTrigger with no month, no day-of-month and no week, so Set-ScheduledTask
cannot write back a trigger that lost its schedule on the way out. Measured on this exact task.
Unlike the catch-up fix this one is a value FLIP, not an insert, so there is no element-ordering
question to answer.

Exits 2 on the wrong machine, 3 if the task is missing, 4 if the setting is not present to flip,
1 if verification fails.
#>
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

$EXPECT_HOST = 'SECILPT-UPKZHVS'
$TASK        = '\BD\Finance\Patrimonio Monthly'

if ($env:COMPUTERNAME -ne $EXPECT_HOST) {
    Write-Host "REFUSING: this is $EXPECT_HOST's task. Current host: $env:COMPUTERNAME." -ForegroundColor Yellow
    exit 2
}

$xml = (schtasks /query /tn $TASK /xml ONE 2>$null | Out-String)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($xml)) {
    Write-Host "REFUSING: cannot read $TASK on this machine." -ForegroundColor Red
    exit 3
}

if ($xml -match '<DisallowStartIfOnBatteries>\s*false\s*</DisallowStartIfOnBatteries>') {
    Write-Host "ALREADY ALLOWED: DisallowStartIfOnBatteries is already false -- nothing to do." -ForegroundColor Green
    exit 0
}
if ($xml -notmatch '<DisallowStartIfOnBatteries>\s*true\s*</DisallowStartIfOnBatteries>') {
    Write-Host "REFUSING: expected <DisallowStartIfOnBatteries>true</> and did not find it." -ForegroundColor Red
    Write-Host "  The task is not the shape this script was written against (measured 2026-08-19)."
    exit 4
}

$before      = Get-ScheduledTask -TaskPath '\BD\Finance\' -TaskName 'Patrimonio Monthly'
$wasDisabled = ($before.State -eq 'Disabled')
$beforeTrig  = ([xml]$xml).Task.Triggers.InnerXml
$beforeAct   = ([xml]$xml).Task.Actions.InnerXml
$beforePrn   = ([xml]$xml).Task.Principals.InnerXml
$beforeNext  = ($before | Get-ScheduledTaskInfo).NextRunTime

$fixed = $xml -replace '<DisallowStartIfOnBatteries>\s*true\s*</DisallowStartIfOnBatteries>',
                       '<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'

if ($DryRun) {
    Write-Host "`nDRY RUN -- nothing was changed." -ForegroundColor Yellow
    Write-Host "  would set : DisallowStartIfOnBatteries true -> false"
    Write-Host "  would keep: StopIfGoingOnBatteries=$($before.Settings.StopIfGoingOnBatteries) (deliberate -- a killed Excel COM write is worse than no run)"
    Write-Host "  would keep: StartWhenAvailable=$($before.Settings.StartWhenAvailable), day 27, next run $beforeNext"
    exit 0
}

# schtasks emits and expects UTF-16LE with a BOM.
$tmp = Join-Path $env:TEMP 'patrimonio_battery.xml'
[System.IO.File]::WriteAllText($tmp, $fixed, [System.Text.UnicodeEncoding]::new($false, $true))
& schtasks /create /tn $TASK /xml $tmp /f 2>&1 | Out-Null
$rc = $LASTEXITCODE
Remove-Item $tmp -ErrorAction SilentlyContinue

if ($rc -ne 0) {
    Write-Host "FAILED: schtasks exited $rc. The task is UNCHANGED." -ForegroundColor Red
    Write-Host "  Set it by hand: Task Scheduler -> Properties -> Conditions -> clear"
    Write-Host "  'Start the task only if the computer is on AC power'."
    exit 1
}

# --- verify from the task itself ---------------------------------------------------------
$checkXml = (schtasks /query /tn $TASK /xml ONE 2>$null | Out-String)
$after    = Get-ScheduledTask -TaskPath '\BD\Finance\' -TaskName 'Patrimonio Monthly'

$fail = @()
if ($checkXml -notmatch '<DisallowStartIfOnBatteries>\s*false\s*</DisallowStartIfOnBatteries>') {
    $fail += "DisallowStartIfOnBatteries did not stick"
}
if ($after.Settings.DisallowStartIfOnBatteries)  { $fail += "the task object still refuses to start on battery" }
if (-not $after.Settings.StopIfGoingOnBatteries) { $fail += "StopIfGoingOnBatteries was turned OFF -- it must stay ON" }
if (-not $after.Settings.StartWhenAvailable)     { $fail += "StartWhenAvailable was lost" }
if ($checkXml -notmatch '<Day>27</Day>')         { $fail += "day 27 is GONE from the trigger" }
if (([xml]$checkXml).Task.Actions.InnerXml    -ne $beforeAct)  { $fail += "the ACTION changed" }
if (([xml]$checkXml).Task.Principals.InnerXml -ne $beforePrn)  { $fail += "the PRINCIPAL changed" }
if ((([xml]$checkXml).Task.Triggers.InnerXml) -ne $beforeTrig) {
    Write-Host "note    the trigger XML was re-serialized (expected; the day is asserted above)." -ForegroundColor Yellow
}
if (($after.State -eq 'Disabled') -ne $wasDisabled) { $fail += "enabled state moved to $($after.State)" }

if ($fail.Count) {
    Write-Host "`nFAILED:" -ForegroundColor Red
    $fail | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

Write-Host "`nOK: the patrimony chain may now START on battery." -ForegroundColor Green
Write-Host "    DisallowStartIfOnBatteries=$($after.Settings.DisallowStartIfOnBatteries)  " -NoNewline
Write-Host "StopIfGoingOnBatteries=$($after.Settings.StopIfGoingOnBatteries) (kept ON, deliberately)"
Write-Host "    StartWhenAvailable=$($after.Settings.StartWhenAvailable), day 27, $($after.State)"
Write-Host "    next run: $(($after | Get-ScheduledTaskInfo).NextRunTime)   (was $beforeNext)"
Write-Host ""
Write-Host "JUDGE IT BY LastTaskResult AFTER 2026-08-27, NOT BY State:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTaskInfo -TaskPath '\BD\Finance\' -TaskName 'Patrimonio Monthly'"
Write-Host "  0x41303 = SCHED_S_TASK_HAS_NOT_RUN, i.e. it has still never run. 0 = it ran."
exit 0
