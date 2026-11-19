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
# Newer versions add folders to the data folder (e.g. documents); give them the same delete protection.
$envFile = "$AppDir\faults.env"
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern '^\s*FAULTS_DATA_DIR\s*=\s*(.+)$' | Select-Object -First 1
    if ($m) {
        $dataDir = $m.Matches[0].Groups[1].Value.Trim().Trim('"')
        if (Test-Path $dataDir) {
            try { Protect-Subfolder $dataDir "documents" }
            catch { Write-Warning "Couldn't protect the documents folder: $($_.Exception.Message)" }
        }
    }
}
if (Test-AppHealth) { Write-Host "Updated and restarted. The app can open its database." -ForegroundColor Green }
else { Write-Warning "The app restarted but can't open its database. Check $AppDir\logs\DamageTrackerWeb.log." }
& "$AppDir\deploy\windows\add-shortcut.ps1" -AppDir $AppDir
