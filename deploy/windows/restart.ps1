<#
  Check for a new version, start or restart the Damage Tracker, and show the addresses to open it on.
  The desktop shortcut "Damage Tracker - Start or Restart" runs this.
  It asks for administrator rights because Windows services need them to restart.
#>
param([string]$AppDir = (Split-Path (Split-Path $PSScriptRoot)))

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-AppDir", "`"$AppDir`"")
    exit
}

$Host.UI.RawUI.WindowTitle = "Damage Tracker"

# Check GitHub for a newer version and offer to install it.
function Invoke-UpdateCheck {
    if (-not (Get-Command git -ErrorAction SilentlyContinue) -or -not (Test-Path (Join-Path $AppDir ".git"))) {
        Write-Host "Can't check for updates (git or the code folder's history is missing)." -ForegroundColor Yellow
        return
    }
    Push-Location $AppDir
    try {
        Write-Host "Checking for a new version..." -ForegroundColor Cyan
        git fetch --quiet origin main 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Host "  Couldn't reach GitHub, so skipping the update check." -ForegroundColor Yellow; return }
        $behind = [int](git rev-list --count HEAD..origin/main)
        if ($behind -eq 0) { Write-Host "  You have the latest version."; return }
        Write-Host "  A new version is available ($behind change$(if ($behind -ne 1) {'s'})):" -ForegroundColor Green
        git log --no-merges --format="    - %s" HEAD..origin/main | Select-Object -First 15 | ForEach-Object { Write-Host $_ }
        $answer = Read-Host "  Install it now? Your data is not touched. (Y/N)"
        if ($answer -notmatch '^(y|yes)$') { Write-Host "  Not updating this time."; return }
        git pull --ff-only --quiet origin main
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "  Couldn't apply the update automatically (for example, the code folder has local changes). Nothing was changed."
            return
        }
        & (Join-Path $AppDir "deploy\windows\update.ps1") -AppDir $AppDir | Out-Host
        return
    } finally { Pop-Location }
}
Invoke-UpdateCheck
Write-Host ""
Write-Host "Starting the Damage Tracker..." -ForegroundColor Cyan
$ok = $true
foreach ($name in "DamageTrackerWeb", "DamageTrackerCaddy") {
    try {
        $svc = Get-Service $name -ErrorAction Stop
        if ($svc.Status -eq "Running") { Restart-Service $name -Force -ErrorAction Stop }
        else { Start-Service $name -ErrorAction Stop }
        Write-Host "  $name is running."
    } catch {
        $ok = $false
        Write-Warning "  Couldn't start ${name}: $($_.Exception.Message)"
    }
}

. (Join-Path $PSScriptRoot "protect-data.ps1")
if (Test-AppHealth 30) {
    Write-Host "`nThe Damage Tracker is running." -ForegroundColor Green
} else {
    $ok = $false
    Write-Warning "The program didn't answer. Check $AppDir\logs\DamageTrackerWeb.log."
}

# Plain HTTP unless faults.env turns HTTPS on.
$scheme = "http"
$envFile = Join-Path $AppDir "faults.env"
if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*FAULTS_HTTPS\s*=\s*(1|true|yes|on)\s*$' -Quiet)) {
    $scheme = "https"
}

Write-Host "`nOpen one of these on a phone or PC on the same network:" -ForegroundColor Cyan
Write-Host ("  {0}://{1}.local" -f $scheme, $env:COMPUTERNAME.ToLower()) -ForegroundColor White
$ips = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
    ForEach-Object { $_.IPv4Address.IPAddress } | Where-Object { $_ -and $_ -notlike "169.254.*" }
if (-not $ips) {
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254.*" } |
        ForEach-Object { $_.IPAddress }
}
foreach ($ip in $ips) { Write-Host "  ${scheme}://$ip" -ForegroundColor White }
if (-not $ips) { Write-Warning "This PC doesn't seem to be connected to a network." }

if (-not $ok) { Write-Host "`nSomething went wrong above." -ForegroundColor Yellow }
Write-Host ""
Read-Host "Press Enter to close this window"
