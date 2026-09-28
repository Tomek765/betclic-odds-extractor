<#
  Live end-to-end test of APEX Context Engine - FIXED on a real Betclic match.
  Runs the program's built-in --release-e2e mode with an isolated data folder,
  then shows whether extraction, the odds package and the match context passed.
#>
Set-StrictMode -Version 3
$ErrorActionPreference = "Stop"

$Installed = Join-Path $env:LOCALAPPDATA "Programs\APEX_Context_Engine_FIXED_2026-09-27\APEX_Context_Engine.exe"
$Local = Join-Path $PSScriptRoot "APEX_Context_Engine.exe"
$Exe = if (Test-Path $Installed) { $Installed } elseif (Test-Path $Local) { $Local } else { $null }
if (-not $Exe) { Write-Host "BLAD: nie znaleziono APEX_Context_Engine.exe" -ForegroundColor Red; Read-Host "Enter"; exit 1 }

$Url = Read-Host "Wklej link do meczu Betclic PRZED rozpoczeciem (prematch)"
if (-not $Url) { exit 1 }
$Data = Join-Path $env:LOCALAPPDATA ("APEX_FIXED_LIVE_TEST_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$env:APEX_DATA_DIR = $Data
Write-Host "Uruchamiam test na zywo (1-3 minuty). Otworzy sie okno przegladarki - nie zamykaj go." -ForegroundColor Cyan
try {
    $proc = Start-Process -FilePath $Exe -ArgumentList @("--release-e2e", $Url) -Wait -PassThru
} finally { Remove-Item Env:\APEX_DATA_DIR }

$Out = Join-Path $Data "release_self_test"
$ResultPath = Join-Path $Out "SELF_TEST_RESULT.json"
if (-not (Test-Path $ResultPath)) { Write-Host "BLAD: brak wyniku testu (kod $($proc.ExitCode))" -ForegroundColor Red; Read-Host "Enter"; exit 1 }
$r = Get-Content $ResultPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Show([string]$name, $value) { Write-Host ("{0,-24} {1}" -f $name, $value) }
Write-Host ""
Show "PROGRAM" $r.runtime_executable
Show "EKSTRAKCJA" $r.extract_status
Show "KURSY (zaakceptowane)" $r.odds_count
Show "NIEROZWIAZANE" $r.unresolved_count
Show "KONTEKST" $r.context_status
Show "PAKIET != KONTEKST" $r.products_distinct
Show "BEZ SMIECI TECHNICZNYCH" $r.products_clean
Show "PAKIET (bajty)" $r.odds_package_bytes
Show "KONTEKST (bajty)" $r.context_bytes
if ($r.PSObject.Properties.Name -contains "quarantine_summary" -and $r.quarantine_summary) {
    Write-Host ""; Write-Host "KWARANTANNA / POZA MODELEM (dyspozycja:etap:przyczyna = liczba):"
    $r.quarantine_summary.PSObject.Properties | ForEach-Object { Write-Host ("  {0} = {1}" -f $_.Name, $_.Value) }
}
Write-Host ""
if ($r.passed) { Write-Host "WYNIK: PASS" -ForegroundColor Green } else { Write-Host "WYNIK: FAIL (szczegoly w SELF_TEST_RESULT.json)" -ForegroundColor Red }
Write-Host "Pliki: APEX_ODDS_PACKAGE.txt (pakiet), APEX_CONTEXT_REPORT.txt (kontekst), APEX_QUARANTINE_DIAGNOSTICS.json"
Start-Process explorer.exe $Out
Read-Host "Nacisnij Enter, aby zamknac"
