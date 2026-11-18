<#
  Apply a new version of the program. Run as Administrator after replacing the code in C:\DamageTracker
  (for example with "git pull"). Your data, faults.env and Caddyfile are not touched.
#>
param([string]$AppDir = "C:\DamageTracker")
$ErrorActionPreference = "Stop"
$venvPy = "$AppDir\.venv\Scripts\python.exe"
$nssm = "$AppDir\tools\nssm.exe"
Push-Location $AppDir
& $nssm stop DamageTrackerWeb
& $venvPy -m pip install -r requirements.txt
& $venvPy manage.py migrate --noinput
& $venvPy manage.py collectstatic --noinput | Out-Null
& $nssm start DamageTrackerWeb
Pop-Location
. "$AppDir\deploy\windows\protect-data.ps1"
if (Test-AppHealth) { Write-Host "Updated and restarted. The app can open its database." -ForegroundColor Green }
else { Write-Warning "The app restarted but can't open its database. Check $AppDir\logs\DamageTrackerWeb.log." }
