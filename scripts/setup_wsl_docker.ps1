# Check / enable the free WSL2 + Docker Engine setup used by the recovery drills.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_wsl_docker.ps1 -Check
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_wsl_docker.ps1 -Apply   # needs admin
#
# -Check  : read-only diagnostics, no elevation needed.
# -Apply  : enables VirtualMachinePlatform + WSL (DISM), then asks for a reboot.
#           It cannot change BIOS settings: VT-x must be enabled by a human.

[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$problems = New-Object System.Collections.Generic.List[string]
$notes = New-Object System.Collections.Generic.List[string]

function Write-Section([string]$title) {
    Write-Host ""
    Write-Host "== $title" -ForegroundColor Cyan
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$isAdmin = Test-Admin

Write-Section "Host"
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs = Get-CimInstance Win32_ComputerSystem
$freeGb = [math]::Round((Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace / 1GB, 1)
Write-Host ("OS      : {0}" -f $os.Caption)
Write-Host ("CPU     : {0} ({1}C/{2}T)" -f $cpu.Name.Trim(), $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)
Write-Host ("RAM     : {0} GB" -f [math]::Round($cs.TotalPhysicalMemory / 1GB, 1))
Write-Host ("C: free : {0} GB" -f $freeGb)
Write-Host ("Admin   : {0}" -f $isAdmin)

Write-Section "Virtualization"
Write-Host ("VirtualizationFirmwareEnabled : {0}" -f $cpu.VirtualizationFirmwareEnabled)
Write-Host ("HypervisorPresent             : {0}" -f $cs.HypervisorPresent)
if (-not $cpu.VirtualizationFirmwareEnabled) {
    $notes.Add("BIOS reports virtualization disabled. Enable Intel VT-x / AMD SVM in BIOS, then reboot.")
    $notes.Add("Windows 11 Home has no Hyper-V, but WSL2 only needs Virtual Machine Platform + VT-x.")
}

Write-Section "Windows features (needs admin to query)"
$featureNames = @('VirtualMachinePlatform', 'Microsoft-Windows-Subsystem-Linux')
$featureState = @{}
foreach ($name in $featureNames) {
    $state = "unknown"
    if ($isAdmin) {
        try {
            $state = (Get-WindowsOptionalFeature -Online -FeatureName $name -ErrorAction Stop).State
        } catch {
            $state = "query-failed"
        }
    } else {
        # DISM can report state without admin only in limited cases; try and fall back.
        $out = (dism.exe /online /get-featureinfo /featurename:$name 2>&1 | Out-String)
        if ($out -match 'State\s*:\s*(\w+)') { $state = $Matches[1] }
    }
    $featureState[$name] = $state
    Write-Host ("{0,-40} : {1}" -f $name, $state)
    if ($state -ne 'Enabled') {
        $problems.Add("Windows feature '$name' is $state (expected Enabled).")
    }
}

Write-Section "WSL"
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($null -eq $wsl) {
    $problems.Add("wsl.exe not found.")
} else {
    $wslVersion = (& wsl.exe --version 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0) {
        Write-Host (($wslVersion -split "`r?`n" | Select-Object -First 3) -join " | ")
    } else {
        $notes.Add("Artifact: 'wsl --version' failed; WSL2 may not be installed yet.")
    }
    $status = (& wsl.exe --status 2>&1 | Out-String)
    if ($status -match 'WSL2|2') { Write-Host "wsl --status: ok (see raw output below)" }
    Write-Host ($status.Trim() | Select-Object -First 8)
    $dists = (& wsl.exe -l -v 2>&1 | Out-String)
    if ($dists -match 'Ubuntu') {
        Write-Host "Ubuntu distro: present"
    } else {
        $problems.Add("No Ubuntu distro installed yet (wsl --install -d Ubuntu).")
    }
}

Write-Section "Docker"
$docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($null -eq $docker) {
    $notes.Add("docker CLI not found. Docker Engine will be installed inside Ubuntu, not on Windows.")
} else {
    $version = (& docker.exe version --format '{{.Server.Version}}' 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -eq 0 -and $version -notmatch 'error|Cannot') {
        Write-Host ("Docker engine reachable, server {0}" -f $version)
    } else {
        $notes.Add("docker CLI exists but engine is not reachable: $version")
    }
}

if ($Apply) {
    Write-Section "Apply"
    if (-not $isAdmin) {
        Write-Host "ERROR: -Apply needs an elevated PowerShell (Run as administrator)." -ForegroundColor Red
        exit 2
    }
    $changed = $false
    foreach ($name in $featureNames) {
        if ($featureState[$name] -ne 'Enabled') {
            Write-Host ("Enabling {0} ..." -f $name)
            $result = dism.exe /online /enable-feature /featurename:$name /all /norestart
            $result | Write-Host
            if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3010) {
                Write-Host ("dism failed for {0} (exit {1})" -f $name, $LASTEXITCODE) -ForegroundColor Red
                exit 3
            }
            if ($LASTEXITCODE -eq 3010) { $changed = $true }
            $changed = $true
        }
    }
    if ($changed) {
        Write-Host ""
        Write-Host "Features enabled. Reboot Windows, then run:" -ForegroundColor Yellow
        Write-Host "  wsl --update"
        Write-Host "  wsl --set-default-version 2"
        Write-Host "  wsl --install -d Ubuntu"
        exit 0
    }
    Write-Host "Nothing to change: features already enabled."
}

Write-Section "Summary"
if ($problems.Count -eq 0) {
    Write-Host "READY: host looks ready for WSL2 + Docker Engine drills." -ForegroundColor Green
} else {
    Write-Host "NOT READY:" -ForegroundColor Yellow
    foreach ($p in $problems) { Write-Host (" - {0}" -f $p) }
}
if ($notes.Count -gt 0) {
    Write-Host "Notes:"
    foreach ($n in $notes) { Write-Host (" * {0}" -f $n) }
}

if (-not $Check -and -not $Apply) {
    Write-Host ""
    Write-Host "Usage: -Check (read-only) or -Apply (enable Windows features, needs admin)."
}

if ($problems.Count -gt 0 -or -not $Check) { exit 1 } else { exit 0 }
