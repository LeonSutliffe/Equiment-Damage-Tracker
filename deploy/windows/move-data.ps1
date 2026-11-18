<#
  Move the database and photos out of the program folder into a protected folder.
  Run in PowerShell as Administrator:

    powershell -ExecutionPolicy Bypass -File C:\DamageTracker\deploy\windows\move-data.ps1

  What it does, in order. It stops at the first problem and leaves everything as it was.
   1. Stops the web app so nothing changes during the copy.
   2. Copies the database, secret key and photos to C:\ProgramData\DamageTracker\data.
   3. Checks the copy: database integrity, same number of rows in every table,
      and every photo compared byte for byte.
   4. Points the app at the new folder (FAULTS_DATA_DIR in faults.env) and starts it again.
   5. Checks the app answers.
   6. Locks the new folder so it can't be deleted by accident (see protect-data.ps1).
  The old folder is NOT deleted. It is renamed to data.old-<date> so nothing uses it by mistake.
  Delete it yourself once you're happy, or keep it as a spare copy.
#>
param(
    [string]$AppDir = "C:\DamageTracker",
    [string]$NewDataDir = "C:\ProgramData\DamageTracker\data"
)
$ErrorActionPreference = "Stop"
function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Please run this script in PowerShell opened with 'Run as administrator'."
}
. "$AppDir\deploy\windows\protect-data.ps1"
$nssm = "$AppDir\tools\nssm.exe"
$venvPy = "$AppDir\.venv\Scripts\python.exe"
$envFile = "$AppDir\faults.env"

# Where is the data now?
$oldDataDir = "$AppDir\data"
$current = Get-Content $envFile -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*FAULTS_DATA_DIR\s*=' } | Select-Object -Last 1
if ($current) { $oldDataDir = ($current -split "=", 2)[1].Trim().Trim('"') }
if ((Resolve-Path $oldDataDir -ErrorAction SilentlyContinue).Path -eq $NewDataDir) {
    Write-Host "The data is already in $NewDataDir. Making sure it's protected."
    Protect-DataFolder $NewDataDir
    exit 0
}
if (-not (Test-Path "$oldDataDir\db.sqlite3")) { throw "No database found at $oldDataDir\db.sqlite3. Nothing was changed." }
if (Test-Path "$NewDataDir\db.sqlite3") { throw "$NewDataDir already has a database. Nothing was changed." }
Write-Host "Moving data from $oldDataDir to $NewDataDir"

Step "Stopping the web app"
& $nssm stop DamageTrackerWeb | Out-Null
Start-Sleep -Seconds 2

$switched = $false
try {
    Step "Copying and checking"
    & $venvPy -I "$AppDir\deploy\windows\copy_data.py" $oldDataDir $NewDataDir
    if ($LASTEXITCODE -ne 0) { throw "The copy didn't check out. The app still uses $oldDataDir." }

    Step "Pointing the app at the new folder"
    Copy-Item $envFile "$envFile.bak-before-move" -Force
    $lines = Get-Content $envFile | Where-Object { $_ -notmatch '^\s*FAULTS_DATA_DIR\s*=' }
    $lines += "FAULTS_DATA_DIR=$NewDataDir"
    $lines | Set-Content -Encoding UTF8 $envFile
    $switched = $true

    Step "Starting the web app"
    & $nssm start DamageTrackerWeb | Out-Null
    $ok = $false
    for ($i = 0; $i -lt 20 -and -not $ok; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:8000/login/" -UseBasicParsing -MaximumRedirection 0 -ErrorAction Stop
            $ok = $r.StatusCode -eq 200
        } catch {
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -in 301, 302) { $ok = $true }
        }
    }
    if (-not $ok) { throw "The app didn't answer after the move." }
} catch {
    Write-Warning $_
    if ($switched) {
        Write-Warning "Switching back to the old folder."
        Copy-Item "$envFile.bak-before-move" $envFile -Force
    }
    & $nssm restart DamageTrackerWeb | Out-Null
    Write-Warning "Nothing was deleted. The app is using $oldDataDir as before. The partial copy in $NewDataDir can be deleted."
    exit 1
}

Step "Locking the new folder"
Protect-DataFolder $NewDataDir

Step "Retiring the old folder"
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$retired = "$oldDataDir.old-$stamp"
try {
    # The old folder may itself be locked against deletion (which also blocks renaming); unlock just that copy.
    & icacls $oldDataDir /reset /T /C /Q | Out-Null
    Rename-Item $oldDataDir $retired
    Write-Host "The old folder is now $retired. It is a complete spare copy; delete it when you're happy."
} catch {
    Write-Warning "Couldn't rename $oldDataDir ($_). It's no longer used; it's a complete spare copy."
}

Write-Host "`nDone. Your database and photos now live in $NewDataDir and are protected from accidental deletion." -ForegroundColor Green
