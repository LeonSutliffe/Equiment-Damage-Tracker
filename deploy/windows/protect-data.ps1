<#
  Lock the tracker's data folder so it can't be deleted by accident.
  Dot-sourced by install.ps1 and move-data.ps1; can also be run on its own as Administrator:

    powershell -ExecutionPolicy Bypass -File C:\DamageTracker\deploy\windows\protect-data.ps1 -DataDir C:\ProgramData\DamageTracker\data

  After this:
  - Normal (non-administrator) accounts, including programs you run day to day, can only READ the folder.
  - Administrators and the app's Windows service can add and change data, but Windows refuses to
    delete the folder, the database file, the secret key or any photo.
  - The app itself never deletes these files (removed photos are only hidden), so it keeps working.
  To delete it deliberately one day, first run:  icacls "<folder>" /reset /T
#>
param([string]$DataDir)

function Protect-DataFolder([string]$Dir) {
    if (-not (Test-Path $Dir)) { throw "Data folder $Dir doesn't exist." }
    $admins = "*S-1-5-32-544"   # Administrators
    $system = "*S-1-5-18"       # SYSTEM (the Windows services run as this)
    $users  = "*S-1-5-32-545"   # Users

    # Replace inherited permissions with our own: full control for SYSTEM and admins, read-only for everyone else.
    & icacls $Dir /inheritance:r /grant:r "${system}:(OI)(CI)F" "${admins}:(OI)(CI)F" "${users}:(OI)(CI)RX" /T /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Couldn't set permissions on $Dir" }

    # Nobody may delete the folder itself or remove things directly from it...
    & icacls $Dir /deny "${admins}:(DE,DC)" "${users}:(DE,DC)" /Q | Out-Null
    # ...nor the database and secret key...
    foreach ($f in "db.sqlite3", "secret_key.txt") {
        $p = Join-Path $Dir $f
        if (Test-Path $p) { & icacls $p /deny "${admins}:(DE)" "${users}:(DE)" /Q | Out-Null }
    }
    # ...nor any photo, now or in the future.
    $photos = Join-Path $Dir "photos"
    New-Item -ItemType Directory -Force -Path $photos | Out-Null
    & icacls $photos /deny "${admins}:(OI)(CI)(DE,DC)" "${users}:(OI)(CI)(DE,DC)" /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Couldn't protect $photos" }
    Write-Host "Protected $Dir against deletion (normal accounts can only read it)."
}

if ($DataDir) { Protect-DataFolder $DataDir }
