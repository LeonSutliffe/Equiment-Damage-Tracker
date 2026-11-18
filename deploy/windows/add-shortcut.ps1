<#
  Put a "Damage Tracker - Start or Restart" shortcut on the desktop (all users).
  install.ps1 and update.ps1 run this; it is safe to run again.
#>
param([string]$AppDir = (Split-Path (Split-Path $PSScriptRoot)))
try {
    $desktop = [Environment]::GetFolderPath("CommonDesktopDirectory")
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $desktop "Damage Tracker - Start or Restart.lnk"))
    $link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$AppDir\deploy\windows\restart.ps1`""
    $link.WorkingDirectory = $AppDir
    $link.IconLocation = "$env:SystemRoot\System32\shell32.dll,238"
    $link.Description = "Start or restart the Damage Tracker and show its address"
    $link.Save()
    Write-Host "Desktop shortcut 'Damage Tracker - Start or Restart' is ready."
} catch {
    Write-Warning "Couldn't create the desktop shortcut: $($_.Exception.Message)"
}
