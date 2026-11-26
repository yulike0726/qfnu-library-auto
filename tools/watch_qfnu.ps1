# QFNU library watchdog: keeps one `cli daily` daemon alive per account profile.
# Started detached (WMI) so it survives DSH/session restarts and command exit.
# NOTE: keep this file free of non-ASCII literals - it runs under Windows
# PowerShell 5.1, which decodes BOM-less scripts as ANSI.
$ErrorActionPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
# python comes from %QFNU_PYTHON%, else PATH; no local path baked in
$python = if ($env:QFNU_PYTHON) { $env:QFNU_PYTHON } else { 'python' }
$logDir = Join-Path $root 'logs'
$watchLog = Join-Path $logDir 'watchdog.log'

$daemonVbs = Join-Path $PSScriptRoot 'qfnu_daemon.vbs'

$accounts = @(
    @{ name = 'main'; profile = '';    log = (Join-Path $logDir 'task.log') },
    @{ name = 'qzm';  profile = 'qzm'; log = (Join-Path $logDir 'task-qzm.log') }
)

function Write-WatchLog($text) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$stamp watchdog: $text" | Out-File -FilePath $watchLog -Append -Encoding utf8
}

function Get-Daemons {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'qfnu_lib\.cli daily' } |
        ForEach-Object {
            [pscustomobject]@{
                pid     = $_.ProcessId
                profile = if ($_.CommandLine -match '--profile\s+(\S+)') { $matches[1] } else { '' }
            }
        }
}

function Start-Daemon($acct) {
    # go through the VBS launcher: the daemon then owns a hidden console of its
    # own and is not killed when this process (or the harness console) goes away
    $cmd = 'wscript.exe //nologo "' + $daemonVbs + '" ' + $acct.profile
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine      = $cmd
        CurrentDirectory = $root
    }
    Write-WatchLog ("started " + $acct.name + " daemon (return=" + $r.ReturnValue + " pid=" + $r.ProcessId + ")")
}

# single instance guard (named mutex: immune to matching the parent shell's command line)
$mutex = New-Object System.Threading.Mutex($false, 'Global\qfnu_library_watchdog')
if (-not $mutex.WaitOne(0)) { exit }

Write-WatchLog ("up; root=" + $root)

$running = Get-Daemons
foreach ($acct in $accounts) {
    if (-not ($running | Where-Object { $_.profile -eq $acct.profile })) { Start-Daemon $acct }
}

while ($true) {
    Start-Sleep -Seconds 45
    $running = Get-Daemons
    foreach ($acct in $accounts) {
        if (-not ($running | Where-Object { $_.profile -eq $acct.profile })) {
            Write-WatchLog ("missing " + $acct.name + " daemon, restarting")
            Start-Daemon $acct
        }
    }
}