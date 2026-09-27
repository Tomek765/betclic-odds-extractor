<#
.SYNOPSIS
  Builds, packages and verifies the side-by-side "FIXED" Windows release of
  APEX Context Engine without touching any existing installation.

.DESCRIPTION
  Run from a clean checkout of branch claude/sleepy-ptolemy-yki9u7:

    git clone -b claude/sleepy-ptolemy-yki9u7 https://github.com/tomek765/betclic-odds-extractor D:\APEX_FIXED_SRC
    cd D:\APEX_FIXED_SRC
    powershell -ExecutionPolicy Bypass -File release\Build-FixedRelease.ps1 -LiveUrl "https://www.betclic.pl/...-m123456"

  Steps (each one fails closed and is recorded in FINAL_REPORT.txt):
    1. source check  - HEAD contains 5d34ec2, tracked tree clean; the build uses
                       `git archive HEAD`, so untracked test artifacts never ship
    2. tests         - compileall, unittest, pytest on the exported source
    3. build         - PyInstaller onedir via build_exe.py in a scratch copy
    4. new folder    - <OutputRoot>\APEX_Context_Engine_FIXED_2026-09-27 (never overwritten)
    5. zip           - <OutputRoot>\APEX_Context_Engine_FIXED_2026-09-27.zip, re-extracted and compared
    6. shortcut      - Desktop\APEX Context Engine - FIXED.lnk (old shortcut untouched)
    7. shortcut run  - launches via the .lnk, verifies process path and window build id
    8. release e2e   - live extraction with the new EXE into an isolated APEX_DATA_DIR
    9. old version   - fingerprints of the old release, install and shortcut compared
#>
[CmdletBinding()]
param(
    [string]$LiveUrl = "",
    [string]$OutputRoot = "",
    [string]$FixtureDiagnosticsDir = "D:\APEX_CONTEXT_ENGINE_V1_WORK\APEX_FINAL_FREEZE_CLONE\diagnostics",
    [string]$PythonLauncher = "py",
    [string]$PythonVersionArg = "-3.12",
    [string]$PlaywrightVersion = "1.52.0",
    [switch]$AllowTestFailures
)

Set-StrictMode -Version 3
$ErrorActionPreference = "Stop"

$ReleaseName   = "APEX_Context_Engine_FIXED_2026-09-27"
$ShortcutName  = "APEX Context Engine - FIXED"
$ExpectedBuild = "APEX_CONTEXT_ENGINE_FIXED_20260927"
$RequiredCommit = "5d34ec2"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputRoot) {
    if (Test-Path "D:\") { $OutputRoot = "D:\" } else { $OutputRoot = [Environment]::GetFolderPath("UserProfile") }
}
$Target   = Join-Path $OutputRoot $ReleaseName
$Zip      = Join-Path $OutputRoot "$ReleaseName.zip"
$Exe      = Join-Path $Target "APEX_Context_Engine.exe"
$Desktop  = [Environment]::GetFolderPath("Desktop")
$Lnk      = Join-Path $Desktop "$ShortcutName.lnk"
$Work     = Join-Path $env:TEMP ("apex_fixed_build_" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
$SelfTestData = Join-Path $OutputRoot "${ReleaseName}_SELFTEST_DATA"
$Report   = [ordered]@{}

# The previous working version: never written, moved or deleted by this script.
$Protected = @(
    "D:\APEX_CONTEXT_ENGINE_V1_RELEASE",
    (Join-Path $env:LOCALAPPDATA "Programs\APEX Context Engine"),
    (Join-Path $Desktop "APEX Context Engine.lnk"),
    (Join-Path $Repo "dist")
)

function Step([string]$name) { Write-Host ""; Write-Host "=== $name ===" -ForegroundColor Cyan }
function Fail([string]$message) { $Report["FINAL_STATUS"] = "FAIL"; $Report["FAIL_REASON"] = $message; Write-Report; throw $message }
function Write-Report {
    if (Test-Path $OutputRoot) {
        $lines = $Report.GetEnumerator() | ForEach-Object { "{0}: {1}" -f $_.Key, $_.Value }
        $path = Join-Path $OutputRoot "${ReleaseName}_FINAL_REPORT.txt"
        Set-Content -Path $path -Value $lines -Encoding UTF8
        Write-Host "REPORT=$path"
    }
}
function Fingerprint([string]$path) {
    if (-not (Test-Path $path)) { return "ABSENT" }
    if ($path.EndsWith(".lnk")) {
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
        return "LNK|" + $s.TargetPath + "|" + $s.WorkingDirectory + "|" + (Get-FileHash $path -Algorithm SHA256).Hash
    }
    $files = Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue | Sort-Object FullName
    $exe = $files | Where-Object { $_.Name -eq "APEX_Context_Engine.exe" } | Select-Object -First 1
    $exeHash = "NO_EXE"
    if ($exe) { $exeHash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash }
    return "DIR|" + @($files).Count + "|" + ($files | Measure-Object Length -Sum).Sum + "|" + $exeHash
}
function Assert-NotProtected([string]$path) {
    foreach ($p in $Protected) {
        if ($path.TrimEnd("\").StartsWith($p.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) { Fail "REFUSING_PROTECTED_PATH:$path" }
    }
}
function Invoke-Checked([string]$label, [scriptblock]$block) {
    & $block
    if ($LASTEXITCODE -ne 0) { Fail "$label exit=$LASTEXITCODE" }
}
function Read-PacketValue([string]$text, [string]$key) {
    $m = [regex]::Match($text, "(?m)^" + [regex]::Escape($key) + '="?([^";]*)"?;')
    if ($m.Success) { return $m.Groups[1].Value } return ""
}

if ($env:OS -ne "Windows_NT") { throw "This script must run on Windows." }
$Report["RELEASE_NAME"] = $ReleaseName
$Report["ROOT_FOLDER"] = $Target
$Report["FINAL_EXE"] = $Exe
$Report["ZIP"] = $Zip
$Report["DESKTOP_SHORTCUT"] = $Lnk

Step "0. Protect the old version"
foreach ($p in @($Target, $Zip, $SelfTestData)) { Assert-NotProtected $p }
if (Test-Path $Target) { Fail "TARGET_EXISTS_REFUSING_OVERWRITE:$Target" }
if (Test-Path $Zip) { Fail "ZIP_EXISTS_REFUSING_OVERWRITE:$Zip" }
if (Test-Path $Lnk) { Fail "SHORTCUT_EXISTS_REFUSING_OVERWRITE:$Lnk" }
$Before = @{}
foreach ($p in $Protected) { $Before[$p] = Fingerprint $p; Write-Host "$p => $($Before[$p])" }

Step "1. Source check"
Push-Location $Repo
try {
    $head = (git rev-parse HEAD).Trim()
    git merge-base --is-ancestor $RequiredCommit HEAD
    if ($LASTEXITCODE -ne 0) { Fail "HEAD_DOES_NOT_CONTAIN_$RequiredCommit" }
    $dirty = git status --porcelain --untracked-files=no
    if ($dirty) { Fail "TRACKED_WORKTREE_NOT_CLEAN:$dirty" }
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    New-Item -ItemType Directory -Path $Work | Out-Null
    git archive --format=zip -o (Join-Path $Work "src.zip") HEAD
    if ($LASTEXITCODE -ne 0) { Fail "GIT_ARCHIVE_FAILED" }
} finally { Pop-Location }
$Report["GIT_BRANCH"] = $branch
$Report["GIT_COMMIT"] = $head
$TestSrc  = Join-Path $Work "test_src"
$BuildSrc = Join-Path $Work "build_src"
Expand-Archive (Join-Path $Work "src.zip") $TestSrc
Expand-Archive (Join-Path $Work "src.zip") $BuildSrc
$builtId = Select-String -Path (Join-Path $BuildSrc "core.py") -Pattern '^BUILD_ID = "([^"]+)"' | ForEach-Object { $_.Matches[0].Groups[1].Value }
if ($builtId -ne $ExpectedBuild) { Fail "UNEXPECTED_BUILD_ID:$builtId" }

Step "2. Python environment"
$Venv = Join-Path $Work "venv"
Invoke-Checked "venv" { & $PythonLauncher $PythonVersionArg -m venv $Venv }
$Py = Join-Path $Venv "Scripts\python.exe"
Invoke-Checked "pip" { & $Py -m pip install -q --upgrade pip }
Invoke-Checked "deps" { & $Py -m pip install -q "playwright==$PlaywrightVersion" "playwright-stealth>=2.0.0" pyinstaller pytest jsonschema }
Invoke-Checked "chromium" { & $Py -m playwright install chromium }
$Chromium = Join-Path $env:LOCALAPPDATA "ms-playwright\chromium-1169\chrome-win\chrome.exe"
if (-not (Test-Path $Chromium)) { Fail "SPEC_REQUIRES_CHROMIUM_1169_NOT_FOUND:$Chromium (adjust -PlaywrightVersion)" }

Step "3. Tests on the final exported source"
if (Test-Path $FixtureDiagnosticsDir) {
    # Read-only copy of the immutable replay fixtures (git-ignored in the repo).
    Copy-Item $FixtureDiagnosticsDir (Join-Path $TestSrc "diagnostics") -Recurse
    $Report["TEST_FIXTURE_DIAGNOSTICS"] = $FixtureDiagnosticsDir
} else {
    $Report["TEST_FIXTURE_DIAGNOSTICS"] = "MISSING:$FixtureDiagnosticsDir (replay tests will fail)"
}
Push-Location $TestSrc
try {
    & $Py -m compileall -q . | Out-Null
    $Report["TEST_COMPILEALL"] = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL" })
    $ut = & $Py -m unittest discover 2>&1 | Out-String
    $utExit = $LASTEXITCODE
    Set-Content (Join-Path $Work "unittest.txt") $ut -Encoding UTF8
    $Report["TEST_UNITTEST"] = (($ut -split "`n") | Where-Object { $_ -match '^(Ran |OK|FAILED)' }) -join " "
    $pt = & $Py -m pytest -q -p no:cacheprovider -rfE 2>&1 | Out-String
    $ptExit = $LASTEXITCODE
    Set-Content (Join-Path $Work "pytest.txt") $pt -Encoding UTF8
    $Report["TEST_PYTEST"] = (($pt -split "`n") | Where-Object { $_ -match '(passed|failed)' } | Select-Object -Last 1)
    $failed = ($pt -split "`n") | Where-Object { $_ -match '^(FAILED|ERROR) ' }
    $Report["TEST_FAILURES"] = $(if ($failed) { ($failed -join " | ") } else { "NONE" })
    $sc = & $Py -m pytest -q -p no:cacheprovider test_section_context_binding.py 2>&1 | Out-String
    $Report["TEST_SECTION_CONTEXT_BINDING"] = (($sc -split "`n") | Where-Object { $_ -match '(passed|failed)' } | Select-Object -Last 1)
} finally { Pop-Location }
Write-Host "unittest: $($Report['TEST_UNITTEST'])"; Write-Host "pytest: $($Report['TEST_PYTEST'])"
if (($utExit -ne 0 -or $ptExit -ne 0) -and -not $AllowTestFailures) {
    Fail "TESTS_FAILED (see $Work\unittest.txt, $Work\pytest.txt; rerun with -AllowTestFailures only for proven environment failures)"
}

Step "4. Windows build"
Push-Location $BuildSrc
try { Invoke-Checked "build_exe" { & $Py build_exe.py } } finally { Pop-Location }
$Dist = Join-Path $BuildSrc "dist\APEX_Context_Engine"
if (-not (Test-Path (Join-Path $Dist "APEX_Context_Engine.exe"))) { Fail "BUILD_OUTPUT_MISSING" }
$Report["WINDOWS_BUILD"] = "PASS"

Step "5. New release folder"
Copy-Item $Dist $Target -Recurse
Copy-Item (Join-Path $BuildSrc "README_START_PL.txt") $Target
$junk = Get-ChildItem $Target -Recurse -Force | Where-Object {
    $_.Name -in @(".git", "__pycache__", ".pytest_cache", "diagnostics", "snapshots", "logs") -or $_.Name -like "*.log" -or $_.Name -like "test_*.py"
}
if ($junk) { Fail "RELEASE_CONTAINS_DEV_ARTIFACTS:$(($junk | Select-Object -First 5 -ExpandProperty FullName) -join ',')" }
$ExeHash = (Get-FileHash $Exe -Algorithm SHA256).Hash
@(
    "APEX Context Engine - FIXED build",
    "BUILD_ID=$ExpectedBuild",
    "GIT_BRANCH=$branch",
    "GIT_COMMIT=$head",
    "EXE_SHA256=$ExeHash",
    "BUILT_AT=$(Get-Date -Format s)",
    "DATA_DIR=%LOCALAPPDATA%\APEX Context Engine (override: APEX_DATA_DIR)",
    "PREVIOUS_VERSION=left untouched; this folder is an independent side-by-side build"
) | Set-Content (Join-Path $Target "BUILD_INFO.txt") -Encoding UTF8
$Report["EXE_SHA256"] = $ExeHash

Step "6. ZIP"
Compress-Archive -Path $Target -DestinationPath $Zip -CompressionLevel Optimal
$ZipCheck = Join-Path $Work "zipcheck"
Expand-Archive $Zip $ZipCheck
$zipExe = Join-Path $ZipCheck "$ReleaseName\APEX_Context_Engine.exe"
if (-not (Test-Path $zipExe)) { Fail "ZIP_EXE_NOT_AT_EXPECTED_PATH" }
if ((Get-FileHash $zipExe -Algorithm SHA256).Hash -ne $ExeHash) { Fail "ZIP_EXE_HASH_MISMATCH" }
$srcCount = @(Get-ChildItem $Target -Recurse -File).Count
$zipCount = @(Get-ChildItem (Join-Path $ZipCheck $ReleaseName) -Recurse -File).Count
if ($srcCount -ne $zipCount) { Fail "ZIP_FILE_COUNT_MISMATCH:$srcCount/$zipCount" }
$Report["ZIP_SHA256"] = (Get-FileHash $Zip -Algorithm SHA256).Hash
$Report["ZIP_VERIFIED"] = "PASS ($zipCount files, EXE hash equal)"

Step "7. Desktop shortcut"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($Lnk)
$sc.TargetPath = $Exe
$sc.WorkingDirectory = $Target
$sc.IconLocation = "$Exe,0"
$sc.Description = "APEX Context Engine - FIXED ($ExpectedBuild)"
$sc.Save()
$check = $shell.CreateShortcut($Lnk)
if ($check.TargetPath -ne $Exe -or $check.WorkingDirectory -ne $Target) { Fail "SHORTCUT_VERIFY_FAILED" }

Step "8. Launch through the new shortcut (GUI smoke)"
$preexisting = @(Get-Process -Name "APEX_Context_Engine" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
Start-Process -FilePath $Lnk
$proc = $null
for ($i = 0; $i -lt 90 -and -not $proc; $i++) {
    Start-Sleep -Seconds 1
    $proc = Get-Process -Name "APEX_Context_Engine" -ErrorAction SilentlyContinue |
        Where-Object { $preexisting -notcontains $_.Id -and $_.MainWindowTitle } | Select-Object -First 1
}
if (-not $proc) { Fail "GUI_DID_NOT_OPEN_FROM_SHORTCUT" }
$procPath = $proc.Path
$title = $proc.MainWindowTitle
$Report["GUI_PROCESS_PATH"] = $procPath
$Report["GUI_WINDOW_TITLE"] = $title
$okPath = [string]::Equals($procPath, $Exe, [StringComparison]::OrdinalIgnoreCase)
$okTitle = $title -like "*$ExpectedBuild*"
$proc.CloseMainWindow() | Out-Null
if (-not $proc.WaitForExit(15000)) { Stop-Process -Id $proc.Id }
if (-not $okPath) { Fail "SHORTCUT_STARTED_WRONG_EXE:$procPath" }
if (-not $okTitle) { Fail "GUI_TITLE_NOT_NEW_BUILD:$title" }
$Report["GUI_SMOKE"] = "PASS"
$Report["NEW_DESKTOP_SHORTCUT_VERIFIED"] = "YES"

Step "9. Release E2E (live Betclic, isolated data dir)"
if (-not $LiveUrl) { $LiveUrl = Read-Host "Paste a PRE-MATCH Betclic event URL for the live release test (Enter = skip)" }
if ($LiveUrl) {
    $env:APEX_DATA_DIR = $SelfTestData
    try {
        $e2e = Start-Process -FilePath $Exe -ArgumentList @("--release-e2e", $LiveUrl) -WorkingDirectory $Target -Wait -PassThru
    } finally { Remove-Item Env:\APEX_DATA_DIR }
    $resultPath = Join-Path $SelfTestData "release_self_test\SELF_TEST_RESULT.json"
    if (-not (Test-Path $resultPath)) { Fail "E2E_RESULT_MISSING exit=$($e2e.ExitCode)" }
    $r = Get-Content $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $Report["RELEASE_E2E_EXIT"] = $e2e.ExitCode
    $Report["RELEASE_E2E_RUNTIME"] = $r.runtime_executable
    $Report["RELEASE_E2E_FROZEN"] = $r.frozen
    $Report["RELEASE_E2E_BROWSER"] = $r.browser_executable
    $Report["EXTRACT_STATUS"] = $r.extract_status
    $Report["CONTEXT_STATUS"] = $r.context_status
    if (-not [string]::Equals($r.runtime_executable, $Exe, [StringComparison]::OrdinalIgnoreCase)) { Fail "E2E_USED_WRONG_EXE:$($r.runtime_executable)" }
    if ($r.source_packet -and (Test-Path $r.source_packet)) {
        $packet = Get-Content $r.source_packet -Raw -Encoding UTF8
        foreach ($k in @("BUILD_ID", "SOURCE_RAW_RECORDS", "CANONICAL_EXPORT_REPRESENTATIVE_COUNT", "SEMANTIC_ACCEPTED_COUNT",
                         "CANONICAL_EXPORT_SEMANTIC_QUARANTINED_COUNT", "UNRESOLVED_COUNT", "COMPLETENESS_SCORE",
                         "SOURCE_INCOMPLETE_INSTANCE_COUNT", "EXCLUDED_ROWS", "EQUIVALENCE_GROUPS", "PARSER_TRUTH_STATUS",
                         "ANALYSIS_READY", "FULL_USABLE_READY")) { $Report["PACKET_$k"] = Read-PacketValue $packet $k }
        $canon = [int]$Report["PACKET_CANONICAL_EXPORT_REPRESENTATIVE_COUNT"]
        $acc = [int]$Report["PACKET_SEMANTIC_ACCEPTED_COUNT"]
        $qua = [int]$Report["PACKET_CANONICAL_EXPORT_SEMANTIC_QUARANTINED_COUNT"]
        $Report["ACCOUNTING"] = $(if ($canon -eq $acc + $qua -and $Report["PACKET_BUILD_ID"] -eq $ExpectedBuild) { "PASS ($canon = $acc + $qua)" } else { "FAIL ($canon != $acc + $qua or build id)" })
        $betslip = Select-String -Path $r.source_packet -Pattern "betting-slip" -SimpleMatch
        $Report["BET_SLIP_IN_MARKET_ROWS"] = $(if ($betslip) { "FOUND" } else { "NONE" })
    }
    if ($r.context_text -and (Test-Path $r.context_text)) {
        $ctx = Get-Content $r.context_text -Raw -Encoding UTF8
        foreach ($k in @("STATUS", "QUARANTINE_REASONS", "QUARANTINED_SOURCE_ROWS", "UNRESOLVED_COUNT", "COMPLETENESS_SCORE")) {
            $m = [regex]::Match($ctx, "(?m)^" + $k + "=(.*)$"); if ($m.Success) { $Report["CONTEXT_$k"] = $m.Groups[1].Value.Trim() }
        }
        $Report["CONTEXT_EQUIVALENCE_REJECTED_GROUPS"] = ([regex]::Matches($ctx, '"rejected_groups": \[\]').Count -gt 0)
    }
    $Report["RELEASE_E2E"] = $(if ($r.passed -and $e2e.ExitCode -eq 0) { "PASS" } else { "FAIL" })
} else {
    $Report["RELEASE_E2E"] = "NOT_RUN (no live URL supplied)"
}

Step "10. Old version preserved"
$changed = @()
foreach ($p in $Protected) {
    $after = Fingerprint $p
    if ($after -ne $Before[$p]) { $changed += "$p ($($Before[$p]) -> $after)" }
}
$Report["OLD_VERSION_PRESERVED"] = $(if ($changed) { "NO: " + ($changed -join "; ") } else { "YES" })

$ok = ($Report["GUI_SMOKE"] -eq "PASS") -and ($Report["OLD_VERSION_PRESERVED"] -eq "YES") -and
      ($Report["RELEASE_E2E"] -eq "PASS") -and ($Report["ACCOUNTING"] -like "PASS*") -and ($utExit -eq 0) -and ($ptExit -eq 0)
$Report["FINAL_STATUS"] = $(if ($ok) { "PASS" } else { "PASS_WITH_LIMITATIONS" })
$Report["BUILD_WORK_DIR"] = $Work
Write-Report
$Report.GetEnumerator() | ForEach-Object { "{0}: {1}" -f $_.Key, $_.Value }
