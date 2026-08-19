<#
laptop_fix_task_descriptions.ps1 -- the laptop half of roadmap R13.

RUN THIS ON THE LAPTOP:
  pwsh -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_fix_task_descriptions.ps1 -DryRun
  pwsh -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_fix_task_descriptions.ps1

R13 was written as a vmhost1 problem. It is not: three \BD\Finance tasks on the LAPTOP carry no
description at all, and two of them are the two jobs the laptop OWNS. That is the worse half of
the defect -- on vmhost1 an empty description belongs to a task that is disabled on purpose, so
the silence is at least harmless; here it belongs to jobs that actually run.

Every value below was MEASURED on this machine on 2026-08-19 (Get-ScheduledTask + the task XML),
not copied from a doc. Two of them contradict the docs, and the descriptions say so rather than
repeating the doc:

  StocksPortfolioWeekly  real trigger: weekly WEDNESDAY 12:30   (DaysOfWeek=8, WeeksInterval=1)
                         docs + vault memory say: Mondays 08:30
                         vmhost1's disabled copy says: Monday 08:30 (DaysOfWeek=2) -- so the two
                         machines disagree with each other, not just with the docs.
  Patrimonio Monthly     has NEVER run: LastTaskResult 0x41303 = SCHED_S_TASK_HAS_NOT_RUN, and
                         LastRunTime is the "never" sentinel. StartWhenAvailable is FALSE, so a
                         start missed while the laptop is asleep is DROPPED, not caught up.

Neither of those is fixed here. This script writes descriptions; changing a schedule or a
missed-start policy is a decision, not a comment, and widening a fixer's scope mid-flight is how
guarantees are lost. Both are reported for a decision instead.

  Verify after running:
    Get-ScheduledTask -TaskPath "\BD\Finance\" | Select-Object TaskName,Description | Format-List
#>
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = "Stop"

$EXPECT_HOST = 'SECILPT-UPKZHVS'
if ($env:COMPUTERNAME -ne $EXPECT_HOST) {
    Write-Host "This script describes $EXPECT_HOST's topology. Current host: $env:COMPUTERNAME." -ForegroundColor Yellow
    Write-Host "Refusing to run -- it would write this laptop's paths into another machine's tasks." -ForegroundColor Yellow
    Write-Host "  For vmhost1 use vmhost1_fix_task_descriptions.ps1 instead."
    exit 2
}

$descriptions = @{
    "StocksStrategyMonthly" = @"
Monthly investment-strategy review (/bd-strategy-monthly): re-reads the living guideline doc at Personal\Finance\Strategy\investment_strategy_2026.md and changes allocations ONLY when a documented invalidation trigger has fired.
Trigger : monthly, SECOND WEDNESDAY 09:00
Script  : C:\Github\.scripts\strategy-monthly.bat
Owner   : THIS machine owns this job. vmhost1 has a copy, disabled ON PURPOSE - do not enable it there, or two hosts write the same monthly document.
Why Wed : deliberate, not an artefact - the Claude weekly quota rolls over on Wednesday, so a token-spending monthly job is scheduled where the remainder is not wasted.
WARNING : StartWhenAvailable is TRUE, so a start missed while this laptop was asleep fires as catch-up whenever it wakes - which is why this job has run at 10:24 and 12:24 rather than 09:00. That is deliberate: a monthly review that silently skips a month is worse than one that runs late.
History : carried an hourly Repetition PT1H/PT2H until 2026-08-18 - a MONTHLY job attempting three starts in one day. Removed through the task's own XML (laptop_fix_strategy_monthly_trigger.ps1), because the ScheduledTasks cmdlets do not model this CalendarTrigger and rebuilding the trigger risked losing "second Wednesday".
"@
    "StocksPortfolioWeekly" = @"
Weekly Yahoo-portfolio ingest (portfolio_ingest.py --write): reads the NEWEST Yahoo CSV export sitting in Downloads and refreshes _portfolio_holdings.yaml.
Trigger : weekly WEDNESDAY 12:30
Script  : C:\Github\.scripts\stocks-portfolio-ingest.bat
Owner   : THIS machine owns this job - the Yahoo CSV export lands in THIS machine's Downloads folder. vmhost1 has a copy, disabled on purpose.
WARNING : Yahoo has had no API since 2017, so producing the CSV export is a MANUAL step. This task only ingests whatever is already in Downloads; when the newest export is stale it writes _portfolio_export_stale.txt instead of failing. A green result therefore means "ingested", not "holdings are current".
DECIDED : Wednesday 12:30 is the intended schedule (2026-08-19, roadmap R22). The docs said "Mondays 08:30" and vmhost1's disabled copy was set to it; both are now aligned to this. Beware a false signal: StartWhenAvailable is true, so a Wednesday start missed with the laptop asleep fires on the next wake - the 2026-08-10 and 2026-08-17 runs both landed on a Monday for that reason. A Monday run is NOT evidence of a Monday trigger.
STALE   : the export is re-exported ad-hoc, so a run that finds an unchanged CSV and reports "added/removed/changed: none" is NORMAL, not a failure. When the export is past its age threshold the ingest writes _portfolio_export_stale.txt; since 2026-08-19 the daily digest carries a line naming it, above the numbers it invalidates. Before that, nothing read the file at all.
"@
    "Patrimonio Monthly" = @"
Monthly patrimony pipeline: wages --apply (parses the payslip PDFs) -> audit -> report (Patrimonio.html) -> BankBD refresh_from_excel.bat.
Trigger : monthly, day 27, 09:00
Script  : "C:\Github\BD\Finance\Patrimonio\monthly.cmd"
Logs    : C:\Github\BD\Finance\Patrimonio\logs\monthly_DDMMYYYY.log
Source  : Patrimonio BD.xlsx is the single source of truth. It is password-protected (credential in the .env beside it) and is written through Excel COM on a copy with a timestamped backup - openpyxl would destroy its chartsheets and drawings, so do not "simplify" that path.
HISTORY : this task had NEVER run once (LastTaskResult 0x41303 = SCHED_S_TASK_HAS_NOT_RUN, measured 2026-08-19, registered 2026-08-02). StartWhenAvailable was ABSENT from its Settings, so it defaulted false and a 09:00 start missed with the laptop asleep or off was dropped. Catch-up is now ON (laptop_fix_patrimonio_catchup.ps1, 2026-08-19); day 27 kept deliberately, the payslip PDFs arrive before month end.
WARNING : it may STILL not run. DisallowStartIfOnBatteries is true, so a catch-up on battery is refused; StopIfGoingOnBatteries is true, so an in-flight run is killed if you unplug - and this chain writes the workbook through Excel COM, where a killed write is worse than no run. Left as an open decision (roadmap R23), not silently flipped. Judge this chain by its log, never by the task's result.
"@
}

. (Join-Path $PSScriptRoot '_task_description_engine.ps1')
exit (Invoke-TaskDescriptionFix -Descriptions $descriptions -TaskPath '\BD\Finance\' -DryRun:$DryRun)
