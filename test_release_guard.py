"""Release files agree on the build, and old installers can never downgrade it.

Live 2026-10-02: an old package's installer put the build EXPAND2 back over a
newer one.  Every installer since the first one replaces an installed folder
only when its BUILD_INFO.txt contains "APEX_CONTEXT_ENGINE_FIXED_" (or the
installer's own exact build id), so the release writes BUILD_TAG instead.
"""
import re
import unittest
from pathlib import Path

from core import BUILD_ID, BUILD_SEQ

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "release"
FAMILY = "APEX_CONTEXT_ENGINE_FIXED_"


def read(name):
    return (RELEASE / name).read_text(encoding="utf-8-sig")


class ReleaseFilesAgreeOnTheBuild(unittest.TestCase):
    def test_every_release_script_names_the_current_build(self):
        self.assertIn(f'$BuildId      = "{BUILD_ID}"', read("Instaluj-APEX-FIXED.ps1"))
        self.assertIn(f'$ExpectedBuild = "{BUILD_ID}"', read("Test-Na-Zywo.ps1"))
        self.assertIn(f'$ExpectedBuild = "{BUILD_ID}"', read("Build-FixedRelease.ps1"))
        self.assertIn(BUILD_ID, read("CZYTAJ_MNIE_FIXED.txt").splitlines()[0])
        self.assertIn(BUILD_ID, read("INSTRUKCJA_OBSLUGI_I_INSTALACJI.txt").splitlines()[1])

    def test_build_sequence_is_a_utc_minute(self):
        self.assertRegex(str(BUILD_SEQ), r"^20\d{2}(0[1-9]|1[0-2])([0-2]\d|3[01])([01]\d|2[0-3])[0-5]\d$")
        self.assertTrue(BUILD_ID.startswith(FAMILY))


class OldInstallersCannotDowngrade(unittest.TestCase):
    def test_build_info_is_written_as_build_tag_without_the_family_text(self):
        script = read("Build-FixedRelease.ps1")
        block = script[script.index('"APEX Context Engine - FIXED build",'):script.index('BUILD_INFO.txt") -Encoding UTF8')]
        lines = [line.strip() for line in block.splitlines() if line.strip().startswith('"')]
        self.assertTrue(any(line.startswith('"BUILD_TAG=') for line in lines))
        self.assertTrue(any(line.startswith('"BUILD_SEQ=') for line in lines))
        self.assertFalse(any("BUILD_ID=" in line for line in lines))
        self.assertFalse(any(FAMILY.casefold() in line.casefold() for line in lines))

    def test_new_installer_refuses_downgrades_and_reads_both_formats(self):
        installer = read("Instaluj-APEX-FIXED.ps1")
        self.assertIn('"BUILD_TAG="', installer)
        self.assertIn("$installedRank -gt $newRank", installer)
        self.assertIn("$newestUsedRank -gt $newRank", installer)
        self.assertIn("SendToRecycleBin", installer)

    def test_live_test_runs_its_own_program_and_checks_the_version(self):
        script = read("Test-Na-Zywo.ps1")
        self.assertRegex(script, r"\$Exe = if \(Test-Path \$Local\) \{ \$Local \}")
        self.assertIn("ZLA WERSJA PROGRAMU", script)
        self.assertIn("BUILD_TAG=", script)


if __name__ == "__main__":
    unittest.main()
