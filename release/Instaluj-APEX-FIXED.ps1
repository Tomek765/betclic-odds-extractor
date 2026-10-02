<#
  Installs the side-by-side "FIXED" build of APEX Context Engine for the
  current user and creates the desktop shortcut "APEX Context Engine - FIXED".

  - Copies this extracted folder to
      %LOCALAPPDATA%\Programs\APEX_Context_Engine_FIXED_2026-09-27
    (one stable install folder for every FIXED release, so the shortcut stays).
  - Refuses to replace a NEWER installed or already-used build with an older
    one (live 2026-10-02: an old package's installer silently put the 3-day-old
    build EXPAND2 back).  Lists old APEX packages in Downloads/Desktop and can
    move them to the Recycle Bin after an explicit "T".
  - Never touches the previous version: %LOCALAPPDATA%\Programs\APEX Context Engine,
    its "APEX Context Engine" desktop shortcut or any other folder.
  - Launches the program through the new shortcut and verifies that the
    running process is the new EXE and that its window shows the new build id.
#>
Set-StrictMode -Version 3
$ErrorActionPreference = "Stop"

$InstallName  = "APEX_Context_Engine_FIXED_2026-09-27"
$BuildId      = "APEX_CONTEXT_ENGINE_FIXED_20261002_FAST6"
$BuildTag     = ($BuildId -split "_")[-1]
$BuildFamily  = "APEX_CONTEXT_ENGINE_FIXED_"
$ShortcutName = "APEX Context Engine - FIXED"
$Source  = $PSScriptRoot
$Dest    = Join-Path $env:LOCALAPPDATA "Programs\$InstallName"
$OldDir  = Join-Path $env:LOCALAPPDATA "Programs\APEX Context Engine"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Lnk     = Join-Path $Desktop "$ShortcutName.lnk"
$OldLnk  = Join-Path $Desktop "APEX Context Engine.lnk"
$Exe     = Join-Path $Dest "APEX_Context_Engine.exe"
$Guard   = Join-Path $env:LOCALAPPDATA "APEX Context Engine\NEWEST_BUILD.json"

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }
function Stop-Install([string]$text) { Say "BLAD: $text" Red; Read-Host "Nacisnij Enter, aby zamknac"; exit 1 }

# From FAST3 on BUILD_INFO.txt names the build as BUILD_TAG (e.g. 20261002_FAST3)
# and never contains the text "APEX_CONTEXT_ENGINE_FIXED_": every older
# installer replaces an installed folder only when it finds that text, so an
# old package's installer refuses to put an old build over this one.
function Read-BuildInfo([string]$dir) {
    $info = @{}
    $path = Join-Path $dir "BUILD_INFO.txt"
    if (Test-Path $path) {
        foreach ($line in Get-Content $path) {
            if ($line -match '^([A-Z_0-9]+)=(.*)$') { $info[$Matches[1]] = $Matches[2].Trim() }
        }
    }
    if (-not $info.ContainsKey("BUILD_ID") -and $info.ContainsKey("BUILD_TAG")) {
        $info["BUILD_ID"] = $BuildFamily + $info["BUILD_TAG"]
    }
    return $info
}

# Release order: BUILD_SEQ (UTC yyyymmddHHMM); older builds only have BUILT_AT.
function Get-BuildRank($info) {
    if ($info.ContainsKey("BUILD_SEQ") -and $info["BUILD_SEQ"] -match '^\d{12}$') { return [int64]$info["BUILD_SEQ"] }
    if ($info.ContainsKey("BUILT_AT")) {
        try {
            $when = [datetime]::Parse($info["BUILT_AT"], [Globalization.CultureInfo]::InvariantCulture,
                                      [Globalization.DateTimeStyles]::AdjustToUniversal -bor [Globalization.DateTimeStyles]::AssumeUniversal)
            return [int64]$when.ToString("yyyyMMddHHmm")
        } catch { }
    }
    return [int64]0
}

Say "APEX Context Engine - FIXED ($BuildId)" Cyan
if (-not (Test-Path (Join-Path $Source "APEX_Context_Engine.exe"))) {
    Stop-Install "Uruchom INSTALUJ.cmd z ROZPAKOWANEGO folderu paczki (nie z wnetrza ZIP)."
}
if ([string]::Equals($Dest.TrimEnd("\"), $OldDir.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
    Stop-Install "Docelowy folder pokrywa sie ze stara wersja."
}
$newInfo = Read-BuildInfo $Source
if ($newInfo.ContainsKey("BUILD_ID") -and $newInfo["BUILD_ID"] -ne $BuildId) {
    Stop-Install "BUILD_INFO.txt tej paczki ($($newInfo["BUILD_ID"])) nie zgadza sie z instalatorem ($BuildId)."
}
$newRank = Get-BuildRank $newInfo

# 0. Never install an older build over a newer one.
$installedInfo = Read-BuildInfo $Dest
$installedId = if ($installedInfo.ContainsKey("BUILD_ID")) { $installedInfo["BUILD_ID"] } else { "" }
if ($installedId) { Say "Obecnie zainstalowana wersja: $installedId" }
Say "Ta paczka zawiera wersje:     $BuildId"
$newestUsedId, $newestUsedRank = "", [int64]0
if (Test-Path $Guard) {
    try {
        $g = Get-Content $Guard -Raw | ConvertFrom-Json
        $newestUsedId, $newestUsedRank = [string]$g.build_id, [int64]$g.build_seq
    } catch { }
}
$installedRank = Get-BuildRank $installedInfo
if ($newRank -gt 0 -and $installedRank -gt $newRank) {
    Stop-Install ("Zainstalowana jest NOWSZA wersja ($installedId). Ta paczka ($BuildId) jest STARSZA - " +
                  "instalacja przerwana. Uzyj najnowszej paczki (patrz nazwa ZIP-a).")
}
if ($newRank -gt 0 -and $newestUsedRank -gt $newRank) {
    Stop-Install ("Na tym komputerze byla juz uzywana NOWSZA wersja ($newestUsedId). Ta paczka ($BuildId) jest STARSZA - " +
                  "instalacja przerwana. Uzyj najnowszej paczki.")
}

# 0b. Old packages lying around are how an old build came back: list them.
$scanDirs = @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:USERPROFILE "Downloads")) | Where-Object { $_ -and (Test-Path $_) }
$sourceFullPath = (Resolve-Path $Source).Path
$oldPackages = @(foreach ($dir in $scanDirs) {
    Get-ChildItem $dir -Force -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match '^(APEX_Context_Engine_(FIXED|KOMPLETNY)_|APEX_(EXPAND|FAST|KOMPLETNY)[^ ]*\.zip\.part|ZLOZ_ZIP_)' -and
        $_.Name -notmatch [regex]::Escape($BuildTag) -and
        -not $sourceFullPath.StartsWith($_.FullName, [StringComparison]::OrdinalIgnoreCase)
    }
})
if ($oldPackages.Count -gt 0) {
    Say ""
    Say "Znaleziono STARE paczki APEX (moga przez pomylke zainstalowac stara wersje):" Yellow
    $oldPackages | ForEach-Object { Say ("  " + $_.FullName) Yellow }
    $answer = Read-Host "Przeniesc je do Kosza? Wpisz T i Enter (samo Enter = zostaw)"
    if ($answer -match '^[TtYy]') {
        Add-Type -AssemblyName Microsoft.VisualBasic
        foreach ($item in $oldPackages) {
            try {
                if ($item.PSIsContainer) {
                    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($item.FullName, "OnlyErrorDialogs", "SendToRecycleBin")
                } else {
                    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($item.FullName, "OnlyErrorDialogs", "SendToRecycleBin")
                }
                Say ("  do Kosza: " + $item.Name) Green
            } catch { Say ("  nie udalo sie: " + $item.FullName) Yellow }
        }
    }
    Say ""
}

$oldExe = Join-Path $OldDir "APEX_Context_Engine.exe"
$oldFingerprint = if (Test-Path $oldExe) { (Get-FileHash $oldExe -Algorithm SHA256).Hash } else { "ABSENT" }
$oldLnkFingerprint = if (Test-Path $OldLnk) { (Get-FileHash $OldLnk -Algorithm SHA256).Hash } else { "ABSENT" }

# 1. Copy (a previous copy of this exact FIXED build is refreshed; anything else is refused).
$sourceFull = (Resolve-Path $Source).Path.TrimEnd("\")
if (-not [string]::Equals($sourceFull, $Dest, [StringComparison]::OrdinalIgnoreCase)) {
    if (Test-Path $Dest) {
        $info = Join-Path $Dest "BUILD_INFO.txt"
        # Only an earlier FIXED build installed by this installer is replaced
        # (legacy BUILD_ID line or the BUILD_TAG line of FAST3 and later).
        $isFixed = (Test-Path $info) -and ((Select-String -Path $info -Pattern $BuildFamily -SimpleMatch -Quiet) -or
                                           (Select-String -Path $info -Pattern "BUILD_TAG=" -SimpleMatch -Quiet))
        if (-not $isFixed) {
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
    "PREVIOUS_FIXED_BUILD=$(if ($installedId) { $installedId } else { 'NONE' })",
    "INSTALLED_AT=$(Get-Date -Format s)"
)
$report | Set-Content (Join-Path $Dest "INSTALL_REPORT.txt") -Encoding UTF8
$report | ForEach-Object { Say $_ Green }
Say ""
Say "Gotowe. Program dziala z nowego skrotu na pulpicie: '$ShortcutName'." Cyan
Read-Host "Nacisnij Enter, aby zamknac to okno (program pozostaje otwarty)"
