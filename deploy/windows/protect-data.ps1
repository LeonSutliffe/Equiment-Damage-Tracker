<#
  Lock the tracker's data folder so it can't be deleted by accident.
  Dot-sourced by install.ps1 and move-data.ps1; can also be run on its own as Administrator:

    powershell -ExecutionPolicy Bypass -File C:\DamageTracker\deploy\windows\protect-data.ps1 -DataDir C:\ProgramData\DamageTracker\data

  After this:
  - Normal (non-administrator) accounts, including programs you run day to day, can only READ the folder.
  - Administrators and the app's Windows service can add and change data, but Windows refuses to
    delete the database file, the secret key, any photo or any document (so the folder can't be deleted either).
  - The app itself never deletes these files (removed photos are only hidden), so it keeps working.
  To delete it deliberately one day, first run:  icacls "<folder>" /reset /T
#>
param([string]$DataDir)

function Protect-Subfolder([string]$Dir, [string]$Name) {
    # Nobody may delete files in this subfolder, now or in the future. (Removing one in the app only hides it.)
    $folder = Join-Path $Dir $Name
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    & icacls $folder /deny "*S-1-5-32-544:(OI)(CI)(DE)" "*S-1-5-32-545:(OI)(CI)(DE,DC)" /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Couldn't protect $folder" }
}

function Protect-DataFolder([string]$Dir) {
    if (-not (Test-Path $Dir)) { throw "Data folder $Dir doesn't exist." }
    $admins = "*S-1-5-32-544"   # Administrators
    $system = "*S-1-5-18"       # SYSTEM (the Windows services run as this)
    $users  = "*S-1-5-32-545"   # Users

    # The folder: full control for SYSTEM (the app's service) and admins, read-only for everyone else.
    & icacls $Dir /inheritance:r /grant:r "${system}:(OI)(CI)F" "${admins}:(OI)(CI)F" "${users}:(OI)(CI)RX" /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Couldn't set permissions on $Dir" }
    # Everything inside simply inherits those permissions (this also clears any older, stricter entries).
    if (Get-ChildItem $Dir -Force) {
        & icacls "$Dir\*" /reset /T /C /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Couldn't reset permissions inside $Dir" }
    }

    # Normal accounts may not delete anything in the folder.
    & icacls $Dir /deny "${users}:(DE,DC)" /Q | Out-Null
    # Nobody, not even an administrator, may delete the database or the secret key.
    # (The app never deletes these. SQLite's own -wal/-shm side files are left deletable.)
    foreach ($f in "db.sqlite3", "secret_key.txt") {
        $p = Join-Path $Dir $f
        if (Test-Path $p) { & icacls $p /deny "${admins}:(DE)" "${users}:(DE)" /Q | Out-Null }
    }
    # Nor any photo or document.
    foreach ($sub in "photos", "documents") { Protect-Subfolder $Dir $sub }
    Write-Host "Protected $Dir against deletion (normal accounts can only read it)."
}

function Test-AppHealth([int]$Seconds = 20) {
    # Asks the app to open its database. Returns $true once it answers "ok".
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:8000/health/" -UseBasicParsing -ErrorAction Stop
            if ($r.Content.Trim() -eq "ok") { return $true }
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

if ($DataDir) {
    Protect-DataFolder $DataDir
    $nssm = Join-Path (Split-Path (Split-Path $PSScriptRoot)) "tools\nssm.exe"
    if (Test-Path $nssm) {
        & $nssm restart DamageTrackerWeb | Out-Null
        if (Test-AppHealth) { Write-Host "The app can read and write its database." -ForegroundColor Green }
        else { Write-Warning "The app can't open its database. Check logs\DamageTrackerWeb.log." }
    }
}
