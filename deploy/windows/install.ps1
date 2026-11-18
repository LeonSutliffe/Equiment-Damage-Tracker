<#
  Equipment Damage Tracker: install on a Windows Home desktop PC.
  See deploy/windows/README.md for the full steps. Run in PowerShell **as Administrator**:

    cd C:\DamageTracker
    powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -HostName faults.local

  Safe to run again: existing data, faults.env and Caddyfile are kept.
#>
param(
    [string]$HostName = "faults.local",
    [string]$AppDir = "C:\DamageTracker",
    [string]$Python = "py"
)
$ErrorActionPreference = "Stop"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Please run this script in PowerShell opened with 'Run as administrator'."
}
if (-not (Test-Path "$AppDir\manage.py")) { throw "Can't find $AppDir\manage.py. Copy the program to $AppDir first." }

# Underscores aren't allowed in web addresses, so only add the PC's own name if it's valid.
$pcName = $env:COMPUTERNAME.ToLower()
if ($pcName -notmatch '^[a-z0-9-]+$') { $pcName = $null }
$names = @($HostName) + @($pcName | Where-Object { $_ -and $_ -ne $HostName })

$tools = Join-Path $AppDir "tools"
$nssm  = Join-Path $tools "nssm.exe"
$caddy = Join-Path $tools "caddy.exe"
foreach ($exe in @($nssm, $caddy)) {
    if (-not (Test-Path $exe)) { throw "Missing $exe. See README step 2 (download NSSM and Caddy into $tools)." }
}
New-Item -ItemType Directory -Force -Path "$AppDir\logs", "$AppDir\data", "$AppDir\caddy\data" | Out-Null

Step "Creating Python environment"
if (-not (Test-Path "$AppDir\.venv\Scripts\python.exe")) { & $Python -3 -m venv "$AppDir\.venv" }
$venvPy = "$AppDir\.venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install -r "$AppDir\requirements.txt"

Step "Writing settings (faults.env)"
$envFile = Join-Path $AppDir "faults.env"
if (-not (Test-Path $envFile)) {
    @(
        "FAULTS_ALLOWED_HOSTS=$($names -join ','),localhost,127.0.0.1",
        "FAULTS_CSRF_TRUSTED_ORIGINS=$(($names | ForEach-Object { "https://$_" }) -join ',')",
        "FAULTS_DATA_DIR=$AppDir\data"
    ) | Set-Content -Encoding UTF8 $envFile
    Write-Host "Created $envFile"
} else { Write-Host "Keeping existing $envFile" }

Step "Setting up the database and web files"
Push-Location $AppDir
& $venvPy manage.py migrate --noinput
& $venvPy manage.py collectstatic --noinput | Out-Null
$hasUsers = & $venvPy manage.py shell -v 0 -c "from accounts.models import User; print(User.objects.exists())"
if ("$hasUsers".Trim() -ne "True") {
    Write-Host "`nCreate the first admin account (username and password; email can be left blank):" -ForegroundColor Yellow
    & $venvPy manage.py createsuperuser
}
Pop-Location

Step "Writing Caddy config"
$caddyFile = Join-Path $AppDir "Caddyfile"
if (-not (Test-Path $caddyFile)) {
    (Get-Content "$AppDir\deploy\windows\Caddyfile" -Raw) `
        -replace "C:/DamageTracker", ($AppDir -replace "\\", "/") `
        -replace "(?m)^faults\.local \{", "$($names -join ', ') {" |
        Set-Content -Encoding UTF8 $caddyFile
    Write-Host "Created $caddyFile"
} else { Write-Host "Keeping existing $caddyFile" }
& $caddy validate --config $caddyFile --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw "Caddy didn't accept $caddyFile. Fix it and run this script again." }

Step "Installing Windows services"
function Install-Service($name, $display, $exe, $arguments) {
    $existing = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($existing) { & $nssm stop $name | Out-Null; & $nssm remove $name confirm | Out-Null }
    & $nssm install $name $exe $arguments | Out-Null
    & $nssm set $name DisplayName $display | Out-Null
    & $nssm set $name AppDirectory $AppDir | Out-Null
    & $nssm set $name Start SERVICE_AUTO_START | Out-Null
    & $nssm set $name AppStdout "$AppDir\logs\$name.log" | Out-Null
    & $nssm set $name AppStderr "$AppDir\logs\$name.log" | Out-Null
    & $nssm set $name AppRotateFiles 1 | Out-Null
    & $nssm set $name AppRotateBytes 10485760 | Out-Null
    & $nssm set $name AppExit Default Restart | Out-Null
    & $nssm start $name | Out-Null
    Write-Host "Service $name installed and started"
}
Install-Service "DamageTrackerWeb"   "Damage Tracker - web app" $venvPy "`"$AppDir\serve.py`""
Install-Service "DamageTrackerCaddy" "Damage Tracker - HTTPS (Caddy)" $caddy "run --config `"$caddyFile`" --adapter caddyfile"

Step "Opening the firewall for the local network only"
foreach ($port in 443, 80) {
    $ruleName = "Damage Tracker port $port"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $port `
            -RemoteAddress LocalSubnet -Action Allow -Profile Private,Domain | Out-Null
    }
}
Write-Host "Firewall rules added (ports 80 and 443, local subnet, Private/Domain networks)."
Write-Host "Make sure this PC's network is set to 'Private' in Windows settings."

Step "Exporting the certificate devices need to trust"
$rootCert = "$AppDir\caddy\data\pki\authorities\local\root.crt"
for ($i = 0; $i -lt 20 -and -not (Test-Path $rootCert); $i++) { Start-Sleep -Seconds 1 }
if (Test-Path $rootCert) {
    Copy-Item $rootCert "$AppDir\DamageTracker-root.crt" -Force
    Import-Certificate -FilePath $rootCert -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Write-Host "Root certificate saved to $AppDir\DamageTracker-root.crt and trusted on this PC."
    Write-Host "Install that file once on every phone, tablet and PC that will use the program (README step 6)."
} else {
    Write-Warning "Caddy hasn't created its certificate yet. Check $AppDir\logs\DamageTrackerCaddy.log, then run this script again."
}

Write-Host "`nDone. Open https://$HostName in a browser." -ForegroundColor Green
