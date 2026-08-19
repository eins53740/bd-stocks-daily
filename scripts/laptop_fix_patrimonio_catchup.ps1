<#
laptop_fix_patrimonio_catchup.ps1 -- roadmap R23.

RUN THIS ON THE LAPTOP:
  pwsh -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_fix_patrimonio_catchup.ps1 -DryRun
  pwsh -File C:\Users\bsdias\.claude\skills\bd-stocks-daily\scripts\laptop_fix_patrimonio_catchup.ps1

WHAT. Turns on missed-start catch-up for `\BD\Finance\Patrimonio Monthly` by adding
<StartWhenAvailable>true</StartWhenAvailable> to its Settings. Day 27 at 09:00 stays -- decided
2026-08-19, and it is deliberate: the payslip PDFs the chain parses arrive before month end.

WHY. Measured 2026-08-19: LastTaskResult 0x41303 = SCHED_S_TASK_HAS_NOT_RUN and LastRunTime is the
"never" sentinel. The task has NEVER run. StartWhenAvailable is ABSENT from the exported Settings,
so it defaults to false, and a 09:00 start missed while the laptop is asleep or off is DROPPED
rather than caught up. The action file exists; this is not a broken path. Same argument as
StocksStrategyMonthly: a monthly refresh that silently skips a month is worse than one that runs
late.

WHY XML AND NOT Set-ScheduledTask. This is a MONTHLY task. Get-ScheduledTask returns its
CalendarTrigger as the base MSFT_TaskTrigger with no month, no day-of-month and no week, so
Set-ScheduledTask -Settings would fail with "The parameter is incorrect" -- it cannot write back a
trigger that lost its schedule on the way out. Measured on this exact task 2026-08-19. See
_task_description_engine.ps1 for the full mechanism.

THE ELEMENT ORDER IS NOT GUESSED. Task Scheduler's Settings schema is a sequence, and schtasks
does not export it in the order the documentation suggests (this task exports
DisallowStartIfOnBatteries, StopIfGoingOnBatteries, MultipleInstancesPolicy, IdleSettings). So the
script tries candidate positions and lets `schtasks /create` be the judge: it validates the XML
before replacing anything, so a wrong position fails loudly with the task UNCHANGED.

WHAT THIS DOES NOT FIX, and you should know before trusting it. The same Settings block carries:

    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>

The first means the task will not start at all while the laptop is on battery -- so a catch-up can
still be refused, and this fix alone may not be enough to make the chain run. The second means an
in-flight run is KILLED if the machine goes to battery, and this chain writes to
Patrimonio BD.xlsx through Excel COM; being killed mid-write is worse than not running. Both are
left alone deliberately: they are a real trade-off (a heavy Excel run draining the battery) and
therefore a decision, not a comment. Recorded in roadmap R23.

Exits 2 on the wrong machine, 3 if the task is missing, 4 if the XML is not the shape this script
was written against, 1 if verification fails.
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

# --- assert the shape, and capture what must NOT change ---------------------------------------
foreach ($needle in @('<ScheduleByMonth>', '<Day>27</Day>', '<Settings>')) {
    if ($xml -notmatch [regex]::Escape($needle)) {
        Write-Host "REFUSING: expected '$needle' in the task XML and did not find it." -ForegroundColor Red
        Write-Host "  The task is not the shape this script was written against (measured 2026-08-19)."
        exit 4
    }
}

$before        = Get-ScheduledTask -TaskPath '\BD\Finance\' -TaskName 'Patrimonio Monthly'
$wasDisabled   = ($before.State -eq 'Disabled')
$beforeTrigXml = ([xml]$xml).Task.Triggers.InnerXml
$beforeActXml  = ([xml]$xml).Task.Actions.InnerXml
$beforePrnXml  = ([xml]$xml).Task.Principals.InnerXml
$beforeNext    = ($before | Get-ScheduledTaskInfo).NextRunTime

if ($xml -match '<StartWhenAvailable>\s*true\s*</StartWhenAvailable>') {
    Write-Host "ALREADY ON: StartWhenAvailable is already true -- nothing to do." -ForegroundColor Green
    Write-Host "  next run: $beforeNext"
    exit 0
}
if ($xml -match '<StartWhenAvailable>') {
    # present but false: flip in place, no ordering question to answer.
    $candidates = @(($xml -replace '<StartWhenAvailable>\s*false\s*</StartWhenAvailable>',
                                  '<StartWhenAvailable>true</StartWhenAvailable>'))
    $labels = @('flipped in place')
} else {
    # absent: it must be INSERTED, and Settings is an ordered sequence. Two candidate positions,
    # schtasks validates each.
    $candidates = @(
        ($xml -replace '(\s*)<IdleSettings>', '$1<StartWhenAvailable>true</StartWhenAvailable>$1<IdleSettings>'),
        ($xml -replace '(\s*)</Settings>',    '$1  <StartWhenAvailable>true</StartWhenAvailable>$1</Settings>')
    )
    $labels = @('before <IdleSettings>', 'last inside <Settings>')
}

if ($DryRun) {
    Write-Host "`nDRY RUN -- nothing was changed." -ForegroundColor Yellow
    Write-Host "  current : StartWhenAvailable is $(if ($xml -match '<StartWhenAvailable>') { 'present and false' } else { 'ABSENT (defaults false)' })"
    Write-Host "  day/time: $(if ($xml -match '<Day>27</Day>') { 'day 27' })  next run $beforeNext"
    Write-Host "  would try, in order:"
    for ($i = 0; $i -lt $candidates.Count; $i++) {
        $changed = ($candidates[$i] -ne $xml)
        Write-Host ("    {0}. {1,-24} produces a change: {2}" -f ($i + 1), $labels[$i], $changed)
    }
    Write-Host "`n  NOT touched: DisallowStartIfOnBatteries / StopIfGoingOnBatteries are still true," -ForegroundColor Yellow
    Write-Host "               so a catch-up can still be refused while on battery. See the header." -ForegroundColor Yellow
    exit 0
}

# --- apply: first candidate that both changes the XML and survives schtasks' validation -------
$applied = $null
for ($i = 0; $i -lt $candidates.Count; $i++) {
    $fixed = $candidates[$i]
    if ($fixed -eq $xml) { Write-Host "skip    $($labels[$i]) - no change produced"; continue }

    # schtasks emits and expects UTF-16LE with a BOM.
    $tmp = Join-Path $env:TEMP "patrimonio_swa.xml"
    [System.IO.File]::WriteAllText($tmp, $fixed, [System.Text.UnicodeEncoding]::new($false, $true))

    & schtasks /create /tn $TASK /xml $tmp /f 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $applied = $labels[$i]; Remove-Item $tmp -ErrorAction SilentlyContinue; break }
    Write-Host "reject  $($labels[$i]) - schtasks exited $LASTEXITCODE (task unchanged)" -ForegroundColor Yellow
    Remove-Item $tmp -ErrorAction SilentlyContinue
}

if (-not $applied) {
    Write-Host "FAILED: no candidate position was accepted. The task is UNCHANGED." -ForegroundColor Red
    Write-Host "  Set it by hand: Task Scheduler -> Properties -> Settings -> 'Run task as soon as"
    Write-Host "  possible after a scheduled start is missed'."
    exit 1
}

# --- verify from the task itself ---------------------------------------------------------------
$checkXml = (schtasks /query /tn $TASK /xml ONE 2>$null | Out-String)
$after    = Get-ScheduledTask -TaskPath '\BD\Finance\' -TaskName 'Patrimonio Monthly'

$fail = @()
if ($checkXml -notmatch '<StartWhenAvailable>\s*true\s*</StartWhenAvailable>') { $fail += "StartWhenAvailable did not stick" }
if (-not $after.Settings.StartWhenAvailable)                                   { $fail += "the task object still reports StartWhenAvailable false" }
if ($checkXml -notmatch '<Day>27</Day>')                                       { $fail += "day 27 is GONE from the trigger" }
if (([xml]$checkXml).Task.Actions.InnerXml    -ne $beforeActXml)               { $fail += "the ACTION changed" }
if (([xml]$checkXml).Task.Principals.InnerXml -ne $beforePrnXml)               { $fail += "the PRINCIPAL changed" }
if (($after.State -eq 'Disabled') -ne $wasDisabled)                            { $fail += "enabled state moved to $($after.State)" }

$afterTrigXml = ([xml]$checkXml).Task.Triggers.InnerXml
if ($afterTrigXml -ne $beforeTrigXml) {
    # Not automatically a failure: the XML route re-materializes an empty <Months> as all twelve.
    # It IS a failure if the day moved, which is asserted above. Report it either way.
    Write-Host "note    the trigger XML was re-serialized (expected: empty <Months> becomes all twelve)." -ForegroundColor Yellow
}

if ($fail.Count) {
    Write-Host "`nFAILED:" -ForegroundColor Red
    $fail | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

Write-Host "`nOK: StartWhenAvailable=true via '$applied'. Day 27 09:00, action, principal and the" -ForegroundColor Green
Write-Host "    $($after.State) state are unchanged." -ForegroundColor Green
Write-Host "    next run: $(($after | Get-ScheduledTaskInfo).NextRunTime)   (was $beforeNext)"
Write-Host ""
Write-Host "STILL BLOCKING, deliberately not changed (roadmap R23):" -ForegroundColor Yellow
Write-Host "  DisallowStartIfOnBatteries=$($after.Settings.DisallowStartIfOnBatteries)  " -NoNewline -ForegroundColor Yellow
Write-Host "StopIfGoingOnBatteries=$($after.Settings.StopIfGoingOnBatteries)" -ForegroundColor Yellow
Write-Host "  On battery the catch-up can still be refused, and an in-flight Excel write killed."
exit 0
