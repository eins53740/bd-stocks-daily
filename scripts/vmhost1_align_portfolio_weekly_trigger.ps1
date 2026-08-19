<#
vmhost1_align_portfolio_weekly_trigger.ps1 -- roadmap R22.

RUN THIS ON VMHOST1 -- with powershell.exe, NOT pwsh (there is no real PowerShell 7 there, only
the Store execution alias, which refuses to launch non-interactively):

  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\vmhost1_align_portfolio_weekly_trigger.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\vmhost1_align_portfolio_weekly_trigger.ps1

WHY. Measured 2026-08-19: `\BD\Finance\StocksPortfolioWeekly` runs **Wednesday 12:30** on the
laptop, which owns the job, and **Monday 08:30** here. The two machines disagreed with each other,
not only with the docs. vmhost1's copy is disabled on purpose, so today the divergence costs
nothing -- but this host is the failover (StocksMirrorPull + StocksFailoverWatchdog), and a
failover that silently moves when holdings are ingested is the kind of drift that gets discovered
months later from a wrong cost basis. Wednesday 12:30 is the decision (2026-08-19).

WHY THE CMDLET IS SAFE HERE, when it is not for the monthly tasks. A WEEKLY trigger has a real CIM
class: Get-ScheduledTask returns MSFT_TaskWeeklyTrigger carrying DaysOfWeek and WeeksInterval, so
it round-trips. It is the MONTHLY CalendarTriggers that come back as the base MSFT_TaskTrigger with
no schedule at all and make Set-ScheduledTask fail with "The parameter is incorrect" -- see
_task_description_engine.ps1. Verified on the laptop the same day: writing this task through the
cmdlet left DaysOfWeek = 8 untouched.

SCOPE. Trigger only. It does not touch the action, the principal, the settings, or the enabled
state -- and it asserts all four afterwards, restoring the enabled state if the write moves it.
Two hosts ingesting the same portfolio is worse than two hosts disagreeing about the day.

Exits 2 on the wrong machine, 3 if the task is missing, 4 if the schedule is not the shape this
script was written against, 1 if verification fails.
#>
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

$TASKPATH = '\BD\Finance\'
$TASKNAME = 'StocksPortfolioWeekly'
$WANT_DAY = 'Wednesday'
$WANT_AT  = '12:30'

if ($env:COMPUTERNAME -notmatch 'VMHOST1') {
    Write-Host "REFUSING: this aligns VMHOST1's copy. Current host: $env:COMPUTERNAME." -ForegroundColor Yellow
    Write-Host "  The laptop already runs Wednesday 12:30 and owns the job -- nothing to do there."
    exit 2
}

$task = Get-ScheduledTask -TaskPath $TASKPATH -TaskName $TASKNAME -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "REFUSING: $TASKPATH$TASKNAME does not exist on this machine." -ForegroundColor Red
    exit 3
}

# --- assert the shape before touching anything ------------------------------------------------
if ($task.Triggers.Count -ne 1) {
    Write-Host "REFUSING: expected exactly 1 trigger, found $($task.Triggers.Count)." -ForegroundColor Red
    Write-Host "  Replacing the trigger set would drop the others. Inspect it by hand."
    exit 4
}
$trg = $task.Triggers[0]
if ($trg.CimClass.CimClassName -ne 'MSFT_TaskWeeklyTrigger') {
    Write-Host "REFUSING: trigger is $($trg.CimClass.CimClassName), not MSFT_TaskWeeklyTrigger." -ForegroundColor Red
    Write-Host "  This script's whole safety argument is that a WEEKLY trigger round-trips the cmdlets."
    Write-Host "  A monthly CalendarTrigger does not -- use the XML route instead."
    exit 4
}

$wasDisabled = ($task.State -eq 'Disabled')
$beforeDay   = $trg.DaysOfWeek        # bitmask: 1=Sun 2=Mon 4=Tue 8=Wed 16=Thu 32=Fri 64=Sat
$beforeStart = $trg.StartBoundary
$beforeAct   = ($task.Actions  | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' ;; '
$beforePrn   = "$($task.Principal.UserId)/$($task.Principal.LogonType)/$($task.Principal.RunLevel)"
$beforeSet   = "$($task.Settings.MultipleInstances)/$($task.Settings.StartWhenAvailable)/$($task.Settings.ExecutionTimeLimit)"

Write-Host "current : DaysOfWeek=$beforeDay  StartBoundary=$beforeStart  state=$($task.State)"
Write-Host "target  : $WANT_DAY (8) at $WANT_AT"

if ($beforeDay -eq 8 -and ([datetime]$beforeStart).ToString('HH:mm') -eq $WANT_AT) {
    Write-Host "ALREADY ALIGNED: nothing to do." -ForegroundColor Green
    exit 0
}

if ($DryRun) {
    Write-Host "`nDRY RUN -- nothing was changed." -ForegroundColor Yellow
    Write-Host "  would set : -Weekly -DaysOfWeek $WANT_DAY -At $WANT_AT"
    Write-Host "  would keep: action, principal, settings and the $($task.State) state"
    exit 0
}

# --- write ------------------------------------------------------------------------------------
$new = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WANT_DAY -At $WANT_AT
Set-ScheduledTask -TaskPath $TASKPATH -TaskName $TASKNAME -Trigger $new | Out-Null

# --- verify from the task itself, not from the call returning ---------------------------------
$after = Get-ScheduledTask -TaskPath $TASKPATH -TaskName $TASKNAME

if (($after.State -eq 'Disabled') -ne $wasDisabled) {
    $restore = if ($wasDisabled) { 'Disabled' } else { 'Ready' }
    Write-Host "state moved to $($after.State); restoring $restore" -ForegroundColor Yellow
    if ($wasDisabled) {
        Disable-ScheduledTask -TaskPath $TASKPATH -TaskName $TASKNAME | Out-Null
    } else {
        Enable-ScheduledTask -TaskPath $TASKPATH -TaskName $TASKNAME | Out-Null
    }
    $after = Get-ScheduledTask -TaskPath $TASKPATH -TaskName $TASKNAME
}

$fail = @()
if ($after.Triggers[0].DaysOfWeek -ne 8) { $fail += "DaysOfWeek is $($after.Triggers[0].DaysOfWeek), wanted 8" }
if (([datetime]$after.Triggers[0].StartBoundary).ToString('HH:mm') -ne $WANT_AT) {
    $fail += "time is $(([datetime]$after.Triggers[0].StartBoundary).ToString('HH:mm')), wanted $WANT_AT"
}
$afterAct = ($after.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' ;; '
if ($afterAct -ne $beforeAct) { $fail += "the ACTION changed: '$beforeAct' -> '$afterAct'" }
$afterPrn = "$($after.Principal.UserId)/$($after.Principal.LogonType)/$($after.Principal.RunLevel)"
if ($afterPrn -ne $beforePrn) { $fail += "the PRINCIPAL changed: $beforePrn -> $afterPrn" }
$afterSet = "$($after.Settings.MultipleInstances)/$($after.Settings.StartWhenAvailable)/$($after.Settings.ExecutionTimeLimit)"
if ($afterSet -ne $beforeSet) { $fail += "the SETTINGS changed: $beforeSet -> $afterSet" }
if (($after.State -eq 'Disabled') -ne $wasDisabled) { $fail += "enabled state left at $($after.State)" }

if ($fail.Count) {
    Write-Host "`nFAILED:" -ForegroundColor Red
    $fail | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

Write-Host "`nOK: $TASKNAME is now $WANT_DAY $WANT_AT; action, principal, settings and the" -ForegroundColor Green
Write-Host "    $($after.State) state are unchanged." -ForegroundColor Green
Write-Host "    next run: $(($after | Get-ScheduledTaskInfo).NextRunTime)  (a disabled task reports one anyway)"
exit 0
