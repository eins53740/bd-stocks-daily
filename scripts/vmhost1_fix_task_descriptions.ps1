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
Cause, read from that task's own XML on vmhost1: its <CalendarTrigger> carries an EMPTY
<ScheduleByMonth> body -- no <DaysOfMonth>, no <Months>. The CIM layer behind Set-ScheduledTask
cannot serialize a monthly trigger with neither, and names no parameter when it says so.

This is the same trap laptop_fix_strategy_monthly_trigger.ps1 avoids from the other side: there
the cmdlets risked LOSING the second-Wednesday schedule, here they refuse to write at all. One
conclusion covers both -- for calendar-triggered tasks, go through the task's own XML. So the
write is now cmdlet-first with an XML fallback, and a failure on one task no longer aborts the
rest.

  Verify after running:
    Get-ScheduledTask -TaskPath "\BD\Finance\" | Select-Object TaskName,Description | Format-List
#>
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

# Re-registering a task from its own serialization is lossless by construction -- it is the
# task's own XML going back in unchanged but for the Description. What it is NOT safe for is a
# stored-password principal, so that case refuses instead of guessing a credential.
function Set-DescriptionViaXml {
    param([string]$TaskPath, [string]$Name, [string]$Description)

    $full = "$TaskPath$Name"
    $xml  = (schtasks /query /tn $full /xml ONE 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($xml)) {
        return "could not export the XML for $full"
    }
    if ($xml -notmatch '<RegistrationInfo>') {
        return "no <RegistrationInfo> element in the exported XML"
    }
    if ($xml -match '<LogonType>Password</LogonType>') {
        return "principal uses a stored password -- schtasks /create would need /ru + /rp, and guessing a credential to fix a comment is not a trade worth making. Set this description by hand."
    }

    # XML-escape the text, then protect the .NET replacement-string metacharacter.
    $esc = [System.Security.SecurityElement]::Escape($Description).Replace('$', '$$')

    if ($xml -match '(?s)<RegistrationInfo>.*?<Description>.*?</Description>') {
        $fixed = $xml -replace '(?s)(<RegistrationInfo>.*?)<Description>.*?</Description>', "`${1}<Description>$esc</Description>"
    } else {
        $fixed = $xml -replace '(?s)(<RegistrationInfo>.*?)(\s*)</RegistrationInfo>', "`${1}`${2}  <Description>$esc</Description>`${2}</RegistrationInfo>"
    }
    if ($fixed -eq $xml) { return "the Description injection changed nothing -- unexpected XML shape" }

    # schtasks emits and expects UTF-16LE with a BOM. A UTF-8 file here fails to import, and a
    # UTF-8 BOM written by Out-File is a documented corruption source in this repo.
    $tmp = Join-Path $env:TEMP ("desc_" + $Name + ".xml")
    [System.IO.File]::WriteAllText($tmp, $fixed, [System.Text.UnicodeEncoding]::new($false, $true))

    & schtasks /create /tn $full /xml $tmp /f | Out-Null
    if ($LASTEXITCODE -ne 0) { return "schtasks /create exited $LASTEXITCODE (elevation?)" }
    Remove-Item $tmp -ErrorAction SilentlyContinue
    return $null
}

$failed = @()

foreach ($name in $descriptions.Keys | Sort-Object) {
    $task = Get-ScheduledTask -TaskPath "\BD\Finance\" -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) { Write-Host "SKIP    $name - no such task here"; continue }

    $want = ($descriptions[$name] -replace "`r`n", "`n").TrimEnd()
    $have = if ($task.Description) { ($task.Description -replace "`r`n", "`n").TrimEnd() } else { "" }
    if ($have -eq $want) { Write-Host "OK      $name - already correct"; continue }

    # Two of these four are Disabled ON PURPOSE (the laptop owns them). Two machines writing the
    # same monthly document is far worse than one missing description, so the disabled state is
    # measured before the write and restored if the write moves it.
    $wasDisabled = ($task.State -eq 'Disabled')
    $route = 'cmdlet'

    try {
        $task.Description = $want
        Set-ScheduledTask -InputObject $task -ErrorAction Stop | Out-Null
    } catch {
        Write-Host "CMDLET  $name - refused: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "        falling back to the task's own XML"
        $why = Set-DescriptionViaXml -TaskPath "\BD\Finance\" -Name $name -Description $want
        if ($why) {
            Write-Host "FAILED  $name - $why" -ForegroundColor Red
            $failed += "$name : $why"
            continue          # one task's failure must not skip the others
        }
        $route = 'xml'
    }

    # --- verify from the task itself, not from the fact that the call returned --------------
    $after = Get-ScheduledTask -TaskPath "\BD\Finance\" -TaskName $name
    if (($after.State -eq 'Disabled') -ne $wasDisabled) {
        $restore = if ($wasDisabled) { 'Disabled' } else { 'Ready' }
        Write-Host "        enabled state moved to $($after.State); restoring $restore" -ForegroundColor Yellow
        if ($wasDisabled) {
            Disable-ScheduledTask -TaskPath "\BD\Finance\" -TaskName $name | Out-Null
        } else {
            Enable-ScheduledTask -TaskPath "\BD\Finance\" -TaskName $name | Out-Null
        }
        $after = Get-ScheduledTask -TaskPath "\BD\Finance\" -TaskName $name
        if (($after.State -eq 'Disabled') -ne $wasDisabled) {
            Write-Host "FAILED  $name - could not restore the enabled state" -ForegroundColor Red
            $failed += "$name : left $($after.State), was $restore"
            continue
        }
    }

    $now = if ($after.Description) { ($after.Description -replace "`r`n", "`n").TrimEnd() } else { "" }
    if ($now -ne $want) {
        Write-Host "FAILED  $name - the description did not stick ($route)" -ForegroundColor Red
        $failed += "$name : description not written"
        continue
    }
    Write-Host "UPDATED $name ($route)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Descriptions only. Triggers, actions and principals were not touched."
if ($failed.Count) {
    Write-Host ""
    Write-Host "$($failed.Count) task(s) NOT fixed:" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host "All four descriptions match." -ForegroundColor Green
exit 0
