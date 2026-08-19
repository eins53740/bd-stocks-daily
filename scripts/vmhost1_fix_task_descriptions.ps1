<#
vmhost1-fix-finance-task-descriptions.ps1 -- roadmap R13.

RUN THIS ON VMHOST1:
  pwsh -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\vmhost1_fix_task_descriptions.ps1

It only rewrites the Description text of four \BD\Finance tasks; it touches no trigger, no
action, no principal, and it is idempotent.

WHY IT LIVES IN THE SKILL AND NOT IN .scripts. It has to EXECUTE on vmhost1, and the skills
directory is the only tree with a working push to that machine (the Stop hook plus the
StocksSkillsPush task, hash-verified both ways). `.scripts` has no such mechanism -- that IS
roadmap R10 -- so a copy left only there is a script that can never reach the machine it was
written for, which is exactly the mistake this file is correcting. One copy, in the tree that
travels. When R10 gives the bats a single source, this can move back.

WHY. A Description is the first thing a human reads in Task Scheduler when something breaks,
and on vmhost1 two of them describe the PRE-MIGRATION topology:

  StocksDaily     said  "Trigger : daily 17:00"                        real: daily 13:30
                  said  "Script  : ...C:\Github\BD\Finance\.scripts\"  real: D:\Github\.scripts\
                  said  "Logs    : C:\BD_Obsidian\..."                 real: D:\BD_Obsidian\...
  StocksPrefilter said  "Trigger : daily 16:45 (... has drifted; review)"  real: weekly Mon 14:30
                  said  "Script  : C:\Github\BD\Finance\.scripts\..."      real: D:\Github\.scripts\

and two more carried no description at all (StocksPortfolioWeekly, StocksStrategyMonthly),
which is how a task disabled ON PURPOSE reads identically to one someone switched off and
forgot. Both are disabled here because the LAPTOP owns them -- verified 2026-08-18: they are
Ready on the laptop and Disabled here.

Every value below was measured on vmhost1 on 2026-08-18, not copied from a doc.

RUN 2026-08-18: three of four landed. StocksStrategyMonthly did NOT -- Set-ScheduledTask threw
"The parameter is incorrect." and, because $ErrorActionPreference is Stop, the exception would
have skipped every task after it too (it happened to be last, so nothing was lost this time).
Cause, REPRODUCED on the laptop 2026-08-19 on two monthly tasks, so it is not a vmhost1 oddity:
Set-ScheduledTask cannot round-trip a MONTHLY task on this Windows build at all. Get-ScheduledTask
returns a monthly CalendarTrigger as the BASE class MSFT_TaskTrigger, carrying no month, no
day-of-month and no week -- the schedule is absent from the object. A weekly trigger comes back as
MSFT_TaskWeeklyTrigger with DaysOfWeek and WeeksInterval intact and writes fine. So "The parameter
is incorrect." is Windows refusing to write back a trigger that lost its schedule on the way out.

That makes this the SAME defect laptop_fix_strategy_monthly_trigger.ps1 avoids from the other
side, not a cousin: there the cmdlets would have silently dropped the second-Wednesday schedule,
here Windows refuses instead. Every monthly task on this build is affected. So the
write is now cmdlet-first with an XML fallback, and a failure on one task no longer aborts the
rest. That write path now lives in _task_description_engine.ps1, shared with
laptop_fix_task_descriptions.ps1 -- this file carries only vmhost1's measured table.

  Verify after running:
    Get-ScheduledTask -TaskPath "\BD\Finance\" | Select-Object TaskName,Description | Format-List
#>
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = "Stop"

if ($env:COMPUTERNAME -notmatch "VMHOST1") {
    Write-Host "This script describes VMHOST1's topology. Current host: $env:COMPUTERNAME." -ForegroundColor Yellow
    Write-Host "Refusing to run -- it would write vmhost1 paths into another machine's tasks." -ForegroundColor Yellow
    exit 2
}

$descriptions = @{
    "StocksDaily" = @"
Daily stock evaluation: runs /bd-stocks-daily (1 deep-dive + 2 screens), then emails the digest. Email is sent by this bat (not the skill) so a skipped LLM phase cannot silently swallow it. Skips email if no rows were written for today.
Trigger : daily 13:30
Script  : wscript.exe D:\Github\.scripts\run_hidden.vbs D:\Github\.scripts\stocks-daily.bat
Depends : claude CLI; skill bd-stocks-daily; python send_email.py; D:\Github\BD\BD_Finance; _prefiltered.yaml from StocksPrefilter
Logs    : D:\BD_Obsidian\Personal\Finance\StocksDaily\log\stocks-daily_*.log
WARNING : run_hidden.vbs does NOT wait, so LastTaskResult 0 means "wscript launched", not "the run succeeded". Judge a run by its log and by a _log.csv row for the date -- on 2026-08-17 this task reported 0 while writing no row at all (roadmap R12).
"@
    "StocksPrefilter" = @"
Pre-filter the global ticker universe (Quality Compounder gates + Piotroski + Altman + FCF growth + moat proxy). Writes survivors to _prefiltered.yaml - consumed daily by StocksDaily.
Trigger : weekly Monday 14:30
Script  : wscript.exe D:\Github\.scripts\run_hidden.vbs D:\Github\.scripts\stocks-prefilter.bat
Depends : claude CLI; skill bd-stocks-prefilter; D:\Github\BD\BD_Finance
Logs    : D:\BD_Obsidian\Personal\Finance\StocksDaily\log\stocks-prefilter_*.log
"@
    "StocksPortfolioWeekly" = @"
Weekly Yahoo-portfolio ingest (portfolio_ingest.py --write): reads the newest Yahoo CSV export from Downloads and refreshes _portfolio_holdings.yaml.
DISABLED ON PURPOSE on this host. The LAPTOP owns this job - the Yahoo export lands in the laptop's Downloads folder, and /bd-stocks-monitor stayed there too because vmhost1's OneDrive copy of Patrimonio BD.xlsx is a month stale. Verified 2026-08-18: Ready on the laptop, Disabled here. Do not enable without moving the export path first.
Trigger : weekly Monday 08:30 (would be, if enabled)
Script  : D:\Github\.scripts\stocks-portfolio-ingest.bat
"@
    "StocksStrategyMonthly" = @"
Monthly investment-strategy review (/bd-strategy-monthly): re-reads the living guideline doc and only changes allocations when a documented invalidation trigger has fired.
DISABLED ON PURPOSE on this host - the LAPTOP owns it. Verified 2026-08-18: Ready on the laptop, Disabled here.
Trigger : monthly, 09:00 (would be, if enabled)
Script  : D:\Github\.scripts\strategy-monthly.bat
"@
}

. (Join-Path $PSScriptRoot '_task_description_engine.ps1')
exit (Invoke-TaskDescriptionFix -Descriptions $descriptions -TaskPath '\BD\Finance\' -DryRun:$DryRun)
