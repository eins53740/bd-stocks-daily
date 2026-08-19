<#
_task_description_engine.ps1 -- the shared write path for the \BD\Finance task descriptions.

Dot-sourced by laptop_fix_task_descriptions.ps1 and vmhost1_fix_task_descriptions.ps1. Each of
those carries ONLY its own MEASURED description table and its own hostname guard; the writing,
the fallback, the state guard and the verification live here, once. Two copies of this engine
would drift exactly the way two copies of stocks-daily.bat drifted for ten weeks while everyone
edited the other one (docs/SCHEDULING.md).

It writes descriptions and nothing else: no trigger, no action, no principal. Idempotent.

WHY THERE IS A FALLBACK AT ALL -- and the reason is narrower and worse than first written.
Set-ScheduledTask cannot round-trip a MONTHLY task at all on this Windows build. Measured on the
laptop 2026-08-19, three tasks, same call:

  StocksPortfolioWeekly   MSFT_TaskWeeklyTrigger   DaysOfWeek, WeeksInterval   -> cmdlet OK
  StocksStrategyMonthly   MSFT_TaskTrigger         no schedule property AT ALL -> refused
  Patrimonio Monthly      MSFT_TaskTrigger         no schedule property AT ALL -> refused

Get-ScheduledTask hands back a monthly CalendarTrigger as the BASE class MSFT_TaskTrigger, which
has no month, no day-of-month and no week -- the schedule is simply absent from the object. So
"The parameter is incorrect." is Windows REFUSING to write back a trigger that lost its schedule
on the way out. Had it not refused, it would have written a monthly task with no schedule.

An earlier reading of this blamed an empty <Months> list in the exported XML. That was wrong: the
XML round-trip fills <Months> with all twelve months, and the cmdlet still refuses afterwards. It
is the CIM class, not the XML.

Same defect -- not a cousin -- as the one laptop_fix_strategy_monthly_trigger.ps1 avoids from the
other side: there the cmdlets would have silently dropped a "second Wednesday"; here Windows
refuses instead. One conclusion covers every monthly task on this build: go through the task's
own XML.
#>

# Re-registering a task from its own serialization keeps a WELL-FORMED schedule, because it is
# the task's own XML going back in unchanged but for the Description. Two caveats, both measured:
#
#   * It is not byte-identical. On import Windows re-materializes an empty <Months> list as all
#     twelve months. Semantically equivalent -- day-of-month, week and day-of-week survive and
#     NextRunTime does not move (verified on the laptop, Day 27 and Week 2/Wednesday).
#   * It COMPLETES a DEGENERATE trigger with Windows defaults, and that is a real scope leak.
#     vmhost1's StocksStrategyMonthly exported a <ScheduleByMonth> with no <DaysOfMonth> at all;
#     after the re-register it carries <Day>1</Day>. schtasks /query does render <DaysOfMonth>
#     when it exists (proven on Patrimonio Monthly's Day 27), so the day was genuinely absent and
#     the import chose one. A task with no valid day could never have fired correctly, so this is
#     an improvement -- but it is a TRIGGER change made by a script that promises descriptions
#     only. Before running this against a task whose schedule matters, export its XML and check
#     the trigger is complete.
#
# What this route is NOT safe for is a stored-password principal, so that case refuses instead
# of guessing a credential.
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
    $tmp = Join-Path $env:TEMP ("desc_" + ($Name -replace '[^A-Za-z0-9]', '_') + ".xml")
    [System.IO.File]::WriteAllText($tmp, $fixed, [System.Text.UnicodeEncoding]::new($false, $true))

    & schtasks /create /tn $full /xml $tmp /f | Out-Null
    if ($LASTEXITCODE -ne 0) { return "schtasks /create exited $LASTEXITCODE (elevation?)" }
    Remove-Item $tmp -ErrorAction SilentlyContinue
    return $null
}

function Invoke-TaskDescriptionFix {
    param(
        [Parameter(Mandatory)][hashtable]$Descriptions,
        [string]$TaskPath = '\BD\Finance\',
        [switch]$DryRun
    )

    $failed = @()
    $wrote  = 0

    foreach ($name in $Descriptions.Keys | Sort-Object) {
        $task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) { Write-Host "SKIP    $name - no such task here"; continue }

        $want = ($Descriptions[$name] -replace "`r`n", "`n").TrimEnd()
        $have = if ($task.Description) { ($task.Description -replace "`r`n", "`n").TrimEnd() } else { "" }
        if ($have -eq $want) { Write-Host "OK      $name - already correct"; continue }

        if ($DryRun) {
            $what = if ($have) { "replace $($have.Length) chars" } else { "add a description (has none)" }
            Write-Host "WOULD   $name - $what -> $($want.Length) chars; state $($task.State), logon $($task.Principal.LogonType)" -ForegroundColor Yellow
            continue
        }

        # Some of these tasks are Disabled ON PURPOSE (the other machine owns them). Two hosts
        # writing the same document is far worse than one missing description, so the disabled
        # state is measured before the write and restored if the write moves it.
        $wasDisabled = ($task.State -eq 'Disabled')
        $route = 'cmdlet'

        try {
            $task.Description = $want
            Set-ScheduledTask -InputObject $task -ErrorAction Stop | Out-Null
        } catch {
            Write-Host "CMDLET  $name - refused: $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host "        falling back to the task's own XML"
            $why = Set-DescriptionViaXml -TaskPath $TaskPath -Name $name -Description $want
            if ($why) {
                Write-Host "FAILED  $name - $why" -ForegroundColor Red
                $failed += "$name : $why"
                continue          # one task's failure must not skip the others
            }
            $route = 'xml'
        }

        # --- verify from the task itself, not from the fact that the call returned ------------
        $after = Get-ScheduledTask -TaskPath $TaskPath -TaskName $name
        if (($after.State -eq 'Disabled') -ne $wasDisabled) {
            $restore = if ($wasDisabled) { 'Disabled' } else { 'Ready' }
            Write-Host "        enabled state moved to $($after.State); restoring $restore" -ForegroundColor Yellow
            if ($wasDisabled) {
                Disable-ScheduledTask -TaskPath $TaskPath -TaskName $name | Out-Null
            } else {
                Enable-ScheduledTask  -TaskPath $TaskPath -TaskName $name | Out-Null
            }
            $after = Get-ScheduledTask -TaskPath $TaskPath -TaskName $name
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
        $wrote++
    }

    Write-Host ""
    if ($DryRun) { Write-Host "DRY RUN -- nothing was written."; return 0 }
    Write-Host "Descriptions only. Triggers, actions and principals were not touched."
    if ($failed.Count) {
        Write-Host ""
        Write-Host "$($failed.Count) task(s) NOT fixed:" -ForegroundColor Red
        $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        return 1
    }
    Write-Host "$wrote written, the rest already matched." -ForegroundColor Green
    return 0
}
