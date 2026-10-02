<#
  Live end-to-end test of APEX Context Engine - FIXED on a real Betclic match.
  Runs the program's built-in --release-e2e mode with an isolated data folder,
  then shows whether extraction, the odds package and the match context passed.

  The test always runs the program that ships next to this script (the
  package being tested or, in the install folder, the installed program) and
  fails if the running build is not the build this script belongs to
  (live 2026-10-02: an old build ran unnoticed and old errors came back).
#>
Set-StrictMode -Version 3
$ErrorActionPreference = "Stop"

$ExpectedBuild = "APEX_CONTEXT_ENGINE_FIXED_20261002_FAST7"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\APEX_Context_Engine_FIXED_2026-09-27"
$Installed = Join-Path $InstallDir "APEX_Context_Engine.exe"
$Local = Join-Path $PSScriptRoot "APEX_Context_Engine.exe"
$Exe = if (Test-Path $Local) { $Local } elseif (Test-Path $Installed) { $Installed } else { $null }
if (-not $Exe) { Write-Host "BLAD: nie znaleziono APEX_Context_Engine.exe" -ForegroundColor Red; Read-Host "Enter"; exit 1 }

function Read-BuildId([string]$dir) {
    # BUILD_ID (older builds) or BUILD_TAG (FAST3 and later, see the installer).
    $path = Join-Path $dir "BUILD_INFO.txt"
    if (Test-Path $path) {
        foreach ($line in Get-Content $path) {
            if ($line -match '^BUILD_ID=(.*)$') { return $Matches[1].Trim() }
            if ($line -match '^BUILD_TAG=(.*)$') { return "APEX_CONTEXT_ENGINE_FIXED_" + $Matches[1].Trim() }
        }
    }
    return ""
}
function Field($obj, [string]$name) {
    if ($obj.PSObject.Properties.Name -contains $name) { return $obj.$name }
    return $null
}
function Show([string]$name, $value) { Write-Host ("{0,-30} {1}" -f $name, $value) }

$installedBuild = Read-BuildId $InstallDir
Write-Host ("Testowany program: {0}" -f $Exe) -ForegroundColor Cyan
Write-Host ("Wersja tej paczki: {0}" -f $ExpectedBuild) -ForegroundColor Cyan
if ($installedBuild -and $installedBuild -ne $ExpectedBuild) {
    Write-Host ("UWAGA: zainstalowany program ma inna wersje ({0}). Uruchom INSTALUJ.cmd z tej paczki." -f $installedBuild) -ForegroundColor Yellow
}

$Url = Read-Host "Wklej link do meczu Betclic PRZED rozpoczeciem (prematch)"
if (-not $Url) { exit 1 }
$Data = Join-Path $env:LOCALAPPDATA ("APEX_FIXED_LIVE_TEST_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$env:APEX_DATA_DIR = $Data
Write-Host "Uruchamiam test na zywo (1-3 minuty). Otworzy sie okno przegladarki - nie zamykaj go." -ForegroundColor Cyan
try {
    $proc = Start-Process -FilePath $Exe -ArgumentList @("--release-e2e", $Url) -Wait -PassThru
} finally { Remove-Item Env:\APEX_DATA_DIR }

# Each live test uses its own browser profile (tens of MB); keep the results of
# every test but only the 5 newest profiles.
Get-ChildItem $env:LOCALAPPDATA -Directory -Filter "APEX_FIXED_LIVE_TEST_*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -Skip 5 | ForEach-Object {
        $profileDir = Join-Path $_.FullName "browser_profile"
        if (Test-Path $profileDir) { Remove-Item $profileDir -Recurse -Force -ErrorAction SilentlyContinue }
    }

$Out = Join-Path $Data "release_self_test"
$ResultPath = Join-Path $Out "SELF_TEST_RESULT.json"
if (-not (Test-Path $ResultPath)) { Write-Host "BLAD: brak wyniku testu (kod $($proc.ExitCode))" -ForegroundColor Red; Read-Host "Enter"; exit 1 }
$r = Get-Content $ResultPath -Raw -Encoding UTF8 | ConvertFrom-Json

$runningBuild = [string](Field $r "build_id")
Write-Host ""
Show "PROGRAM" (Field $r "runtime_executable")
Show "WERSJA" $(if ($runningBuild) { $runningBuild } else { "(brak - stara wersja programu)" })
Show "EKSTRAKCJA" (Field $r "extract_status")
Show "KURSY (wszystkie kopie)" (Field $r "odds_count")
Show "KURSY W PAKIECIE (unikalne)" (Field $r "odds_package_rows")
Show "NIEROZWIAZANE" (Field $r "unresolved_count")
Show "ROZWINIETE RYNKI" (Field $r "expanded_market_controls")
Show "NIEROZWINIETE" (Field $r "unexpanded_controls")
Show "RYNKI GRACZY (widok domyslny)" (Field $r "player_expanders_left_at_default_view")
Show "KONTEKST" (Field $r "context_status")
Show "PAKIET != KONTEKST" (Field $r "products_distinct")
Show "BEZ SMIECI TECHNICZNYCH" (Field $r "products_clean")
Show "PAKIET (bajty)" (Field $r "odds_package_bytes")
Show "KONTEKST (bajty)" (Field $r "context_bytes")
$emptyTabs = Field $r "empty_tabs"
if ($emptyTabs) { Show "PUSTE ZAKLADKI (Betclic)" ($emptyTabs -join ", ") }

# Offers without proven Betclic settlement rules are left out of the package
# on purpose; one line is enough (details: APEX_QUARANTINE_DIAGNOSTICS.json).
$summary = Field $r "quarantine_summary"
if ($summary) {
    $left = ($summary.PSObject.Properties | Measure-Object -Property Value -Sum).Sum
    Show "POMINIETE CELOWO" "$left (oferty bez zasad Betclic - nie sa bledem, nie trafiaja do pakietu)"
}
Write-Host ""

$verdict = Field $r "verdict"
if (-not $verdict) { $verdict = if (Field $r "passed") { "PASS" } else { "FAIL" } }
$versionProblem = ""
if ($runningBuild -ne $ExpectedBuild) {
    $versionProblem = "Test uruchomil wersje '$runningBuild', a ta paczka to $ExpectedBuild."
} elseif (Field $r "running_build_outdated") {
    $versionProblem = "Na tym komputerze byla juz uzywana nowsza wersja: $(Field $r 'newest_known_build_id')."
}
if ($versionProblem) {
    Write-Host ("ZLA WERSJA PROGRAMU: " + $versionProblem) -ForegroundColor Red
    Write-Host "Wynik nie dotyczy najnowszego programu. Zainstaluj najnowsza paczke (INSTALUJ.cmd) i powtorz test." -ForegroundColor Red
    $verdict = "FAIL"
}
$structural = Field $r "structural_incomplete_reasons"
if ($structural) { Show "BRAKI STRUKTURALNE" ($structural -join ", ") }
switch ($verdict) {
    "PASS" { Write-Host "WYNIK: PASS" -ForegroundColor Green }
    "PASS_WITH_WARNINGS" {
        $note = if ($emptyTabs) { "Betclic nie pokazal zakladki: $($emptyTabs -join ', ') - reszta danych kompletna, mozna powtorzyc pobranie" } else { "czesc ofert bez rozpoznanej semantyki jest jawnie pominieta" }
        Write-Host "WYNIK: PASS Z OSTRZEZENIAMI ($note)" -ForegroundColor Yellow
    }
    default { Write-Host "WYNIK: FAIL (szczegoly w SELF_TEST_RESULT.json)" -ForegroundColor Red }
}
Write-Host "Pliki: APEX_ODDS_PACKAGE.txt (pakiet), APEX_CONTEXT_REPORT.txt (kontekst), APEX_QUARANTINE_DIAGNOSTICS.json"
Start-Process explorer.exe $Out
Read-Host "Nacisnij Enter, aby zamknac"
