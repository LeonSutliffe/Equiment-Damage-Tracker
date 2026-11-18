<#
  Switch the Damage Tracker to plain HTTP so devices don't need a certificate installed.
  Run in PowerShell as Administrator:

    powershell -ExecutionPolicy Bypass -File C:\DamageTracker\deploy\windows\use-http.ps1

  Afterwards open http://<this PC's IP address> on any device on the work network.
  Your data (C:\DamageTracker\data) is not touched. The old HTTPS Caddyfile is kept as Caddyfile.https.bak.
#>
param([string]$AppDir = "C:\DamageTracker")
$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Please run this script in PowerShell opened with 'Run as administrator'."
}
$nssm = "$AppDir\tools\nssm.exe"
$caddy = "$AppDir\tools\caddy.exe"
$caddyFile = "$AppDir\Caddyfile"
$envFile = "$AppDir\faults.env"

if ((Test-Path $caddyFile) -and -not (Test-Path "$caddyFile.https.bak")) {
    Copy-Item $caddyFile "$caddyFile.https.bak"
}
$logDir = ($AppDir -replace "\\", "/") + "/logs"
@"
# Plain HTTP on port 80 for any address this PC has (written by use-http.ps1).
# The previous HTTPS config is in Caddyfile.https.bak.
:80 {
	request_body {
		max_size 200MB
	}
	reverse_proxy 127.0.0.1:8000
	log {
		output file $logDir/caddy-access.log {
			roll_size 10MiB
			roll_keep 5
		}
	}
}
"@ | Set-Content -Encoding UTF8 $caddyFile
& $caddy validate --config $caddyFile --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw "Caddy didn't accept the new config." }

# Tell the app it is served over HTTP and may be reached by any address (IP or name).
$lines = @()
if (Test-Path $envFile) {
    $lines = Get-Content $envFile | Where-Object { $_ -notmatch '^\s*(FAULTS_HTTPS|FAULTS_ALLOWED_HOSTS)\s*=' }
}
$lines += "FAULTS_HTTPS=0"
$lines += "FAULTS_ALLOWED_HOSTS=*"
$lines | Set-Content -Encoding UTF8 $envFile

& $nssm restart DamageTrackerWeb | Out-Null
& $nssm restart DamageTrackerCaddy | Out-Null

$ip = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
Write-Host "`nDone. Open http://$ip on any device on the work network." -ForegroundColor Green
