<#
.SYNOPSIS
  Removes the hourly <Repetition> block from the LAPTOP's StocksStrategyMonthly trigger.

.DESCRIPTION
  A MONTHLY job must not carry an hourly repetition. Measured 2026-08-18 from the task's own
  XML: CalendarTrigger / ScheduleByMonthDayOfWeek (Week 2, Wednesday, 09:00, every month) with
  Repetition Interval=PT1H Duration=PT2H bolted on. That made a monthly job attempt three
  starts in one day (10:24 / 11:24 / 12:24 on 2026-08-18).

  Two facts the XML corrected about the incident, worth keeping straight:
    * MultipleInstancesPolicy is already IgnoreNew, so only the FIRST of those three actually
      ran -- the other two were refused by Windows, which is exactly where LastTaskResult
      0x800710E0 ("the operator or administrator has refused the request") comes from. The
      repetition was not creating real concurrency; it was creating noise and error results on
      a job that consequently looked broken.
    * StartWhenAvailable=true is what produced the 10:24 start: the machine booted 10:17, the
      09:00 start was missed, and the catch-up fired. Same shape as the 2026-08-15
      growth/daily collision. That setting is LEFT ALONE -- a monthly refresh that silently
      skips a month because the laptop was asleep is worse than one that runs late.

  WHY THE XML ROUND-TRIP AND NOT Set-ScheduledTask:
  the trigger is a CalendarTrigger with ScheduleByMonthDayOfWeek, which the ScheduledTasks
  cmdlets do not model as a first-class trigger type. Clearing Repetition through a rebuilt
  trigger object risks losing the "second Wednesday" -- and a monthly job that starts running
  on the wrong day is a worse defect than the repetition it was meant to fix. Round-tripping
  the task's own serialization is lossless by construction: this script asserts that the ONLY
  difference between the exported and the re-imported XML is the Repetition block.

  Wednesday is deliberate, by the way, not an artefact: the Claude weekly quota rolls over on
  Wednesday, so a token-spending monthly job is scheduled where the remainder is not wasted.

.PARAMETER DryRun
  Show the exported XML, the computed diff and the command that WOULD run -- change nothing.
  Run this first. It needs no elevation.

.EXAMPLE
  pwsh -File .\laptop_fix_strategy_monthly_trigger.ps1 -DryRun
  pwsh -File .\laptop_fix_strategy_monthly_trigger.ps1

.NOTES
  Idempotent: with no Repetition block present it reports "already clean" and exits 0 without
  touching the task. Exits 2 on the wrong machine, 3 if the task is missing, 4 if the XML is
  not the shape this script was written against.
#>
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

$EXPECT_HOST = 'SECILPT-UPKZHVS'
$TASK        = '\BD\Finance\StocksStrategyMonthly'

# --- guard: this task lives on the laptop. On vmhost1 it is disabled ON PURPOSE, because the
# --- laptop owns it, and "fixing" a deliberately-disabled duplicate there would resurrect a
# --- second writer of the same monthly document.
if ($env:COMPUTERNAME -ne $EXPECT_HOST) {
    Write-Host "REFUSING: this script is for $EXPECT_HOST, running on $env:COMPUTERNAME." -ForegroundColor Red
    Write-Host "  On vmhost1 StocksStrategyMonthly is disabled deliberately -- the laptop owns it."
    exit 2
}

# --- read the task's own XML ------------------------------------------------------------
$xml = (schtasks /query /tn $TASK /xml ONE 2>$null | Out-String)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($xml)) {
    Write-Host "REFUSING: cannot read $TASK -- does it exist on this machine?" -ForegroundColor Red
    exit 3
}

# --- assert the shape before touching anything -------------------------------------------
foreach ($needle in @('<ScheduleByMonthDayOfWeek>', '<Week>2</Week>', '<Wednesday />')) {
    if ($xml -notmatch [regex]::Escape($needle)) {
        Write-Host "REFUSING: expected '$needle' in the task XML and did not find it." -ForegroundColor Red
        Write-Host "  The schedule is not the shape this script was written against (measured 2026-08-18)."
        Write-Host "  Re-read the XML before changing anything: schtasks /query /tn `"$TASK`" /xml ONE"
        exit 4
    }
}

if ($xml -notmatch '<Repetition>') {
    Write-Host "ALREADY CLEAN: no <Repetition> block on $TASK -- nothing to do." -ForegroundColor Green
    $nr = (schtasks /query /tn $TASK /fo LIST /v 2>$null | Select-String 'Next Run Time').Line
    if ($nr) { Write-Host "  $($nr.Trim())" }
    exit 0
}

# --- strip ONLY the Repetition block ------------------------------------------------------
# Non-greedy, single block, whitespace-tolerant. Singleline so . spans the newlines inside it.
$fixed = [regex]::Replace($xml, '[ \t]*<Repetition>.*?</Repetition>\s*\r?\n', '',
                          [System.Text.RegularExpressions.RegexOptions]::Singleline)

# --- prove the diff is exactly what was intended -----------------------------------------
$before = ($xml   -split "`r?`n") | Where-Object { $_.Trim() -ne '' }
$after  = ($fixed -split "`r?`n") | Where-Object { $_.Trim() -ne '' }
$gone   = (Compare-Object $before $after | Where-Object SideIndicator -eq '<=').InputObject
$added  = (Compare-Object $before $after | Where-Object SideIndicator -eq '=>').InputObject

Write-Host "`nLines REMOVED (and nothing else):" -ForegroundColor Cyan
$gone | ForEach-Object { Write-Host "  - $($_.Trim())" }
if ($added) {
    Write-Host "REFUSING: the edit ADDED lines, which it must never do:" -ForegroundColor Red
    $added | ForEach-Object { Write-Host "  + $($_.Trim())" }
    exit 4
}
$expected = @('<Repetition>', '<Interval>PT1H</Interval>', '<Duration>PT2H</Duration>', '</Repetition>')
$actual   = @($gone | ForEach-Object { $_.Trim() })
if (Compare-Object $expected $actual) {
    Write-Host "REFUSING: removed lines are not the expected Repetition block." -ForegroundColor Red
    exit 4
}

# schtasks emits and expects UTF-16. Write it back the same way -- a UTF-8 file here fails to
# import, and a UTF-8 BOM written by Out-File is a documented corruption source in this repo.
$tmp = Join-Path $env:TEMP "StocksStrategyMonthly_norepeat.xml"
[System.IO.File]::WriteAllText($tmp, $fixed, [System.Text.UnicodeEncoding]::new($false, $true))

$cmd = "schtasks /create /tn `"$TASK`" /xml `"$tmp`" /f"

if ($DryRun) {
    Write-Host "`nDRY RUN -- nothing was changed." -ForegroundColor Yellow
    Write-Host "  fixed XML written to : $tmp"
    Write-Host "  would run            : $cmd"
    Write-Host "`nRe-run without -DryRun to apply. It will prompt for elevation."
    exit 0
}

# --- apply ---------------------------------------------------------------------------------
Write-Host "`nApplying..." -ForegroundColor Cyan
& schtasks /create /tn $TASK /xml $tmp /f
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: schtasks exited $LASTEXITCODE. The task is unchanged." -ForegroundColor Red
    Write-Host "  If this is an access error, re-run from an elevated pwsh."
    exit $LASTEXITCODE
}

# --- verify from the task itself, not from our own assumption -----------------------------
$check = (schtasks /query /tn $TASK /xml ONE 2>$null | Out-String)
if ($check -match '<Repetition>') {
    Write-Host "FAILED: the Repetition block is STILL present after the import." -ForegroundColor Red
    exit 1
}
foreach ($needle in @('<ScheduleByMonthDayOfWeek>', '<Week>2</Week>', '<Wednesday />')) {
    if ($check -notmatch [regex]::Escape($needle)) {
        Write-Host "FAILED: '$needle' is GONE after the import -- the schedule was damaged." -ForegroundColor Red
        Write-Host "  Restore from the exported XML before the next month's run." -ForegroundColor Red
        exit 1
    }
}

Write-Host "OK: repetition removed, second-Wednesday schedule intact." -ForegroundColor Green
$nr = (schtasks /query /tn $TASK /fo LIST /v 2>$null | Select-String 'Next Run Time|Schedule Type|Days|Repeat: Every').Line
$nr | ForEach-Object { Write-Host "  $($_.Trim())" }
exit 0
