<#
laptop_stagger_task_starts.ps1 -- give every enabled \BD\ task a RandomDelay of 5-25 minutes.

RUN THIS ON THE LAPTOP:
  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_stagger_task_starts.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_stagger_task_starts.ps1

WHY -- and this is NOT the request as first phrased. Asked to delay "the tasks that start at
logon", the measurement said there are none of ours: ALL EIGHT \BD\ tasks with a LogonTrigger are
Disabled, and the 35 enabled logon-triggered tasks on this machine belong to Windows, Office,
Adobe, OneDrive and PowerToys. Delaying those would be modifying system settings, and Windows
servicing resets them anyway.

But the symptom -- a slow logon -- has a real cause in OUR tasks, and it is the same shape:

  * FOUR enabled tasks fire at exactly 09:00: Patrimonio Monthly, StocksStrategyMonthly,
    SyncSapEnv-To-vmhost1, Deslocacoes-Subsidio-Mensal. THREE more at exactly 13:00.
  * ~30 of the ~33 enabled \BD\ tasks carry StartWhenAvailable=true and NONE had a RandomDelay.

StartWhenAvailable means a slot missed while the laptop was asleep or off fires as CATCH-UP on
the next wake. So a 09:30 logon starts the whole missed morning AT ONCE -- which is exactly the
2026-08-15 incident (StocksGrowth and StocksDaily both stamped _1336, both hit their ceilings,
the digest lost) generalised from two tasks to twenty. That incident was fixed for the Stocks
pair by job_lock.ps1; nothing protects the other thirty.

RandomDelay is the right instrument because Task Scheduler applies it to the START, catch-up
starts included. Five to twenty-five minutes, per the owner's decision 2026-08-19.

ONE THING RandomDelay IS NOT: a minimum. Windows draws uniformly from ZERO to the value set, so
a task can still occasionally start on the dot. What this buys is de-correlation -- thirty tasks
no longer start in the same minute -- which is the actual cause of the slow logon. A guaranteed
5-minute floor is not expressible on a calendar or time trigger at all: those have no <Delay>
element (only logon, boot and event triggers do), so a hard floor would mean MOVING each
StartBoundary, changing times that SCHEDULING.md and every task description quote. That trade was
not made silently; ask for it if the de-correlation proves insufficient.

DISTRIBUTED, BUT NOT RANDOM PER RUN. The delay is derived from a hash of the task's own path, so
it is evenly spread across the window AND STABLE: re-running this script does not reshuffle
thirty schedules. A literal Get-Random would make the script's own output unreproducible, which
is a poor trade for a property nobody can observe.

SCOPE. Enabled \BD\ tasks with a time-based trigger. It does NOT touch:
  * \BD\Disabled\*      -- disabled; changing them buys nothing and adds risk
  * LogonTrigger tasks  -- ours are all disabled (see above)
  * anything outside \BD\ -- Windows/Office/vendor tasks are not ours to reschedule
  * a task that ALREADY has a RandomDelay -- a human may have set it deliberately
  * tasks whose principal uses a stored password -- schtasks /create would need /ru + /rp
  * the $EXCLUDE list below, each with its reason

WHY XML AND NOT Set-ScheduledTask. The monthly tasks come back from Get-ScheduledTask as the base
MSFT_TaskTrigger with no schedule at all, so Set-ScheduledTask refuses to write them back ("The
parameter is incorrect"). Rather than use the cmdlets for weekly and XML for monthly, everything
goes through XML -- one path, no per-trigger-type surprises. RandomDelay's position in the
Settings-ordered trigger sequence is not guessed: candidates are tried and `schtasks /create`
validates, which it does BEFORE replacing, so a wrong position fails with the task unchanged.

Exits 2 on the wrong machine, 1 if any task failed to take the delay.
#>
[CmdletBinding()]
param([switch]$DryRun,
      [int]$MinMinutes = 5,
      [int]$MaxMinutes = 25)

$ErrorActionPreference = 'Stop'
$EXPECT_HOST = 'SECILPT-UPKZHVS'

if ($env:COMPUTERNAME -ne $EXPECT_HOST) {
    Write-Host "REFUSING: this describes $EXPECT_HOST's task set. Current host: $env:COMPUTERNAME." -ForegroundColor Yellow
    exit 2
}

# Ordered or in-flight work. Each entry is a reason, not a preference.
$EXCLUDE = @{
    '\BD\TaskTidy-Weekly'         = 'runs 5 min before TaskHealth-Weekly by design; a 25-min delay could invert the pair'
    '\BD\TaskHealth-Weekly'       = 'the other half of that pair'
    '\BD\Finance\StocksSkillsPush' = 'the deployment mechanism itself, and it was Running when this script was written'
}

function Get-StableDelayMinutes {
    <# Even spread across [Min, Max], derived from the task path so it never moves. #>
    param([string]$Key, [int]$Min, [int]$Max)
    $md5   = [System.Security.Cryptography.MD5]::Create()
    $bytes = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Key))
    $n     = [BitConverter]::ToUInt32($bytes, 0)
    return $Min + [int]($n % [uint32]($Max - $Min + 1))
}

$targets = @()
foreach ($t in (Get-ScheduledTask -TaskPath '\BD\*' -ErrorAction SilentlyContinue)) {
    $full = $t.TaskPath + $t.TaskName
    if ($t.State -eq 'Disabled')          { continue }
    if ($t.TaskPath -like '\BD\Disabled\*') { continue }

    $timeTrigs = @($t.Triggers | Where-Object {
        $_.CimClass.CimClassName -ne 'MSFT_TaskLogonTrigger' -and
        $_.CimClass.CimClassName -ne 'MSFT_TaskBootTrigger'  -and
        $_.CimClass.CimClassName -ne 'MSFT_TaskRegistrationTrigger'
    })
    if (-not $timeTrigs.Count) { continue }

    $targets += [pscustomobject]@{
        Full    = $full
        Task    = $t
        Minutes = Get-StableDelayMinutes -Key $full -Min $MinMinutes -Max $MaxMinutes
    }
}

Write-Host "enabled \BD\ tasks with a time trigger: $($targets.Count)"
Write-Host "window: PT${MinMinutes}M .. PT${MaxMinutes}M, spread by a hash of the task path (stable across runs)`n"

$done = @(); $skip = @(); $fail = @()

foreach ($x in ($targets | Sort-Object Full)) {
    $full = $x.Full
    $want = "PT$($x.Minutes)M"

    if ($EXCLUDE.ContainsKey($full)) {
        $skip += "$full -- EXCLUDED: $($EXCLUDE[$full])"
        continue
    }

    $xml = (schtasks /query /tn $full /xml ONE 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($xml)) {
        $skip += "$full -- could not read its XML"
        continue
    }
    if ($xml -match '<LogonType>Password</LogonType>') {
        $skip += "$full -- principal uses a stored password; schtasks /create would need /ru + /rp"
        continue
    }
    if ($xml -match '<RandomDelay>') {
        $cur = ([regex]'<RandomDelay>([^<]+)</RandomDelay>').Match($xml).Groups[1].Value
        $skip += "$full -- already has RandomDelay $cur, left alone"
        continue
    }

    # RandomDelay sits after the base trigger elements and before the ScheduleByX element.
    # Try that first, then last-inside-the-trigger, and let schtasks be the judge.
    $candidates = @(
        @{ label = 'before <ScheduleBy...>'
           xml   = ($xml -replace '(\s*)(<ScheduleBy(?:Day|Week|Month|MonthDayOfWeek)>)', "`$1<RandomDelay>$want</RandomDelay>`$1`$2") },
        @{ label = 'last inside <TimeTrigger>'
           xml   = ($xml -replace '(\s*)(</TimeTrigger>)', "`$1  <RandomDelay>$want</RandomDelay>`$1`$2") },
        @{ label = 'last inside <CalendarTrigger>'
           xml   = ($xml -replace '(\s*)(</CalendarTrigger>)', "`$1  <RandomDelay>$want</RandomDelay>`$1`$2") }
    )

    if ($DryRun) {
        $which = ($candidates | Where-Object { $_.xml -ne $xml } | Select-Object -First 1)
        if ($which) { $done += "$full -> $want  (via $($which.label))" }
        else        { $fail += "$full -- no candidate position produced a change" }
        continue
    }

    $wasDisabled = ($x.Task.State -eq 'Disabled')
    $applied = $null
    foreach ($c in $candidates) {
        if ($c.xml -eq $xml) { continue }
        $tmp = Join-Path $env:TEMP 'stagger_task.xml'
        # schtasks emits and expects UTF-16LE with a BOM.
        [System.IO.File]::WriteAllText($tmp, $c.xml, [System.Text.UnicodeEncoding]::new($false, $true))
        & schtasks /create /tn $full /xml $tmp /f 2>&1 | Out-Null
        $rc = $LASTEXITCODE
        Remove-Item $tmp -ErrorAction SilentlyContinue
        if ($rc -eq 0) { $applied = $c.label; break }
    }

    if (-not $applied) { $fail += "$full -- no candidate position was accepted (task UNCHANGED)"; continue }

    # Verify from the XML, NOT from the CIM object. A monthly CalendarTrigger comes back from
    # Get-ScheduledTask as the base MSFT_TaskTrigger, which has no RandomDelay property at all --
    # so reading $after.Triggers[].RandomDelay reported empty for all seven monthly tasks and
    # called a write that had plainly succeeded a failure. Same defect that makes
    # Set-ScheduledTask refuse these tasks; it bites the read path too.
    $after    = Get-ScheduledTask -TaskPath $x.Task.TaskPath -TaskName $x.Task.TaskName
    $afterXml = (schtasks /query /tn $full /xml ONE 2>$null | Out-String)
    $got      = ([regex]'<RandomDelay>([^<]+)</RandomDelay>').Match($afterXml).Groups[1].Value
    if ($got -ne $want) {
        $fail += "$full -- wrote $want, the task XML reports '$got'"
        continue
    }
    if (($after.State -eq 'Disabled') -ne $wasDisabled) {
        if ($wasDisabled) { Disable-ScheduledTask -TaskPath $x.Task.TaskPath -TaskName $x.Task.TaskName | Out-Null }
        else              { Enable-ScheduledTask  -TaskPath $x.Task.TaskPath -TaskName $x.Task.TaskName | Out-Null }
        $done += "$full -> $want  (via $applied; enabled state restored)"
    } else {
        $done += "$full -> $want  (via $applied)"
    }
}

$verb = if ($DryRun) { 'WOULD SET' } else { 'SET' }
Write-Host "$verb ($($done.Count)):" -ForegroundColor Green
$done | Sort-Object | ForEach-Object { Write-Host "  $_" }

if ($skip.Count) {
    Write-Host "`nSKIPPED ($($skip.Count)), each for a stated reason:" -ForegroundColor Yellow
    $skip | Sort-Object | ForEach-Object { Write-Host "  $_" }
}
if ($fail.Count) {
    Write-Host "`nFAILED ($($fail.Count)):" -ForegroundColor Red
    $fail | Sort-Object | ForEach-Object { Write-Host "  $_" }
}

Write-Host "`nNOT IN SCOPE, deliberately -- reported so the gap is visible, not fixed silently:" -ForegroundColor Cyan
Write-Host "  * 35 enabled LOGON-triggered tasks belong to Windows / Office / Adobe / OneDrive /"
Write-Host "    PowerToys. Rescheduling those is modifying system settings, and Windows servicing"
Write-Host "    resets them. OneDrive already waits PT10M and Adobe PT12M -- both inside 5-25 min."
Write-Host "  * PowerToys 'Autorun for bsdias' waits PT3S and IS a real logon cost, but delaying it"
Write-Host "    means no FancyZones or key remaps for the first minutes. Owner's call:"
Write-Host "      `$t = Get-ScheduledTask -TaskPath '\PowerToys\' -TaskName 'Autorun for bsdias'"
Write-Host "      `$t.Triggers[0].Delay = 'PT5M'; Set-ScheduledTask -InputObject `$t"
Write-Host "  * The HKCU Run key holds 8 autostarts (Edge --win-session-start, Spotify, OneDrive,"
Write-Host "    Adobe Sync, tacky-borders, Lists, the WSL subst) and tacky-borders ALSO has a"
Write-Host "    Startup-folder shortcut -- it launches twice. Registry autostarts are not tasks;"
Write-Host "    they are the other half of a slow logon and want their own pass."

exit ([int]($fail.Count -gt 0))
