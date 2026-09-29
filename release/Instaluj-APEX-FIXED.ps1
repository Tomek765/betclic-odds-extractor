<#
  Installs the side-by-side "FIXED" build of APEX Context Engine for the
  current user and creates the desktop shortcut "APEX Context Engine - FIXED".

  - Copies this extracted folder to
      %LOCALAPPDATA%\Programs\APEX_Context_Engine_FIXED_2026-09-27
  - Never touches the previous version: %LOCALAPPDATA%\Programs\APEX Context Engine,
    its "APEX Context Engine" desktop shortcut or any other folder.
  - Launches the program through the new shortcut and verifies that the
    running process is the new EXE and that its window shows the new build id.
#>
Set-StrictMode -Version 3
$ErrorActionPreference = "Stop"

$ReleaseName  = "APEX_Context_Engine_FIXED_2026-09-27"
$BuildId      = "APEX_CONTEXT_ENGINE_FIXED_20260929_EXPAND2"
$BuildFamily  = "APEX_CONTEXT_ENGINE_FIXED_"
$ShortcutName = "APEX Context Engine - FIXED"
$Source  = $PSScriptRoot
$Dest    = Join-Path $env:LOCALAPPDATA "Programs\$ReleaseName"
$OldDir  = Join-Path $env:LOCALAPPDATA "Programs\APEX Context Engine"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Lnk     = Join-Path $Desktop "$ShortcutName.lnk"
$OldLnk  = Join-Path $Desktop "APEX Context Engine.lnk"
$Exe     = Join-Path $Dest "APEX_Context_Engine.exe"

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }
function Stop-Install([string]$text) { Say "BLAD: $text" Red; Read-Host "Nacisnij Enter, aby zamknac"; exit 1 }

Say "APEX Context Engine - FIXED ($BuildId)" Cyan
if (-not (Test-Path (Join-Path $Source "APEX_Context_Engine.exe"))) {
    Stop-Install "Uruchom instalator z ROZPAKOWANEGO folderu $ReleaseName (nie z wnetrza ZIP)."
}
if ([string]::Equals($Dest.TrimEnd("\"), $OldDir.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
    Stop-Install "Docelowy folder pokrywa sie ze stara wersja."
}
$oldExe = Join-Path $OldDir "APEX_Context_Engine.exe"
$oldFingerprint = if (Test-Path $oldExe) { (Get-FileHash $oldExe -Algorithm SHA256).Hash } else { "ABSENT" }
$oldLnkFingerprint = if (Test-Path $OldLnk) { (Get-FileHash $OldLnk -Algorithm SHA256).Hash } else { "ABSENT" }

# 1. Copy (a previous copy of this exact FIXED build is refreshed; anything else is refused).
$sourceFull = (Resolve-Path $Source).Path.TrimEnd("\")
if (-not [string]::Equals($sourceFull, $Dest, [StringComparison]::OrdinalIgnoreCase)) {
    if (Test-Path $Dest) {
        $info = Join-Path $Dest "BUILD_INFO.txt"
        # Only an earlier FIXED build installed by this installer is replaced.
        if (-not ((Test-Path $info) -and (Select-String -Path $info -Pattern $BuildFamily -SimpleMatch -Quiet))) {
            Stop-Install "Folder $Dest istnieje i nie zawiera buildu FIXED - nie nadpisuje."
        }
        Get-Process -Name "APEX_Context_Engine" -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and $_.Path.StartsWith($Dest, [StringComparison]::OrdinalIgnoreCase) } |
            ForEach-Object { $_.CloseMainWindow() | Out-Null; if (-not $_.WaitForExit(10000)) { Stop-Process -Id $_.Id } }
        Remove-Item $Dest -Recurse -Force
    }
    Say "Kopiowanie do $Dest ..."
    New-Item -ItemType Directory -Path (Split-Path $Dest) -Force | Out-Null
    Copy-Item $Source $Dest -Recurse
}
Get-ChildItem $Dest -Recurse -File | Unblock-File
if (-not (Test-Path $Exe)) { Stop-Install "Brak EXE po kopiowaniu." }

# 2. Desktop shortcut (the old "APEX Context Engine" shortcut is never modified).
$shell = New-Object -ComObject WScript.Shell
if (Test-Path $Lnk) {
    $existing = $shell.CreateShortcut($Lnk)
    if (-not [string]::Equals($existing.TargetPath, $Exe, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Install "Skrot '$ShortcutName' istnieje i wskazuje inny program: $($existing.TargetPath)"
    }
}
$sc = $shell.CreateShortcut($Lnk)
$sc.TargetPath = $Exe
$sc.WorkingDirectory = $Dest
$sc.IconLocation = "$Exe,0"
$sc.Description = "APEX Context Engine - FIXED ($BuildId)"
$sc.Save()
$check = $shell.CreateShortcut($Lnk)
if (-not [string]::Equals($check.TargetPath, $Exe, [StringComparison]::OrdinalIgnoreCase)) { Stop-Install "Weryfikacja skrotu nie powiodla sie." }
Say "Skrot utworzony: $Lnk" Green

# 3. Launch through the shortcut and verify it is the new build.
$before = @(Get-Process -Name "APEX_Context_Engine" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
Start-Process -FilePath $Lnk
$proc = $null
for ($i = 0; $i -lt 90 -and -not $proc; $i++) {
    Start-Sleep -Seconds 1
    $proc = Get-Process -Name "APEX_Context_Engine" -ErrorAction SilentlyContinue |
        Where-Object { $before -notcontains $_.Id -and $_.MainWindowTitle } | Select-Object -First 1
}
if (-not $proc) { Stop-Install "Program nie otworzyl okna w ciagu 90 s." }
if (-not [string]::Equals($proc.Path, $Exe, [StringComparison]::OrdinalIgnoreCase)) { Stop-Install "Skrot uruchomil inny plik: $($proc.Path)" }
if ($proc.MainWindowTitle -notlike "*$BuildId*") { Stop-Install "Okno nie pokazuje nowego buildu: $($proc.MainWindowTitle)" }

$oldAfter = if (Test-Path $oldExe) { (Get-FileHash $oldExe -Algorithm SHA256).Hash } else { "ABSENT" }
$oldLnkAfter = if (Test-Path $OldLnk) { (Get-FileHash $OldLnk -Algorithm SHA256).Hash } else { "ABSENT" }
$preserved = ($oldAfter -eq $oldFingerprint) -and ($oldLnkAfter -eq $oldLnkFingerprint)

$report = @(
    "INSTALL_STATUS=PASS",
    "BUILD_ID=$BuildId",
    "FINAL_EXE=$Exe",
    "EXE_SHA256=$((Get-FileHash $Exe -Algorithm SHA256).Hash)",
    "DESKTOP_SHORTCUT=$Lnk",
    "SHORTCUT_LAUNCH_VERIFIED=YES",
    "RUNNING_PROCESS=$($proc.Path)",
    "WINDOW_TITLE=$($proc.MainWindowTitle)",
    "OLD_VERSION_PRESERVED=$(if ($preserved) { 'YES' } else { 'NO' })",
    "INSTALLED_AT=$(Get-Date -Format s)"
)
$report | Set-Content (Join-Path $Dest "INSTALL_REPORT.txt") -Encoding UTF8
$report | ForEach-Object { Say $_ Green }
Say ""
Say "Gotowe. Program dziala z nowego skrotu na pulpicie: '$ShortcutName'." Cyan
Read-Host "Nacisnij Enter, aby zamknac to okno (program pozostaje otwarty)"
