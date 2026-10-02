"""Regression: odds package and match context are independent products, and
quarantine separates real ambiguity from false positives.

Root causes pinned here:
* APEX_CONTEXT_REPORT.txt (what "ZBUDUJ KONTEKST RYNKU" copies) was rendered
  with the odds-package serializer, so both buttons delivered the odds table.
* False quarantine: short native team names in double chance, corner totals
  "(razem z dogrywką)", documented player-statistic and card periods, one-word
  player names, the scorer+assister pair contract, and proven non-regular
  periods counted as quarantine instead of "not modeled".
"""
import difflib
import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import replay
from apex_context_engine.engine import build_context
from apex_context_engine.market_graph import semantic_safety_quarantine
from apex_context_engine.models import OddRecord
from apex_context_engine.packet_parser import parse_packet_text
from apex_context_engine.report import quarantine_diagnostics, render_match_context, write_outputs
from core import _semantic_quarantine_reason, canonical_export_boundary, llm_packet
from parser import classify_period_detail, parse_market_record
from team_name_evidence import extract_native_team_names
from tests_context.capture_repair_support import capture_packet

ROOT = Path(__file__).parent
FIXTURES = ROOT / "tests_context/fixtures"
MATCH_A = FIXTURES / "kaiserslautern_darmstadt/raw_before_dedupe_run_1788588979_12912.jsonl"
MATCH_B = FIXTURES / "benfica_heart_real/raw_before_dedupe_run_1786040883_6248.jsonl"
MINIMAL = (FIXTURES / "minimal_packet.txt").read_text(encoding="utf-8")
ODDS_HEADER = "FAMILY|MARKET|PERIOD|OWNER|SELECTION|LINE|ODDS|SETTLEMENT"
JUNK = ("MARKET_INSTANCE_ID", "SOURCE_RAW_RECORD_IDS", "RUNTIME_", "SHA256", "BUILD_ID", "RUN_ID",
        "app-desktop[", "marketBox_", "record_mappings", "QUARANTINED_RECORDS", "UPSTREAM_EXCLUSIONS",
        "WARNING_DISPOSITIONS", "source_raw_record_ids")
READY = {"PARSER_TRUTH_STATUS": "PASS", "ANALYSIS_READY": "YES"}


def products(capture: Path) -> dict:
    """The two user products of one extraction, built as the application does."""
    parsed = []
    original = replay.parse_market_record

    def collect(**kwargs):
        row, issue = original(**kwargs)
        if row:
            parsed.append(row)
        return row, issue

    with patch.object(replay, "parse_market_record", side_effect=collect):
        replay.replay_real_prematch(capture)
    home, away = replay._capture_teams(replay.load_real_prematch_fixture(capture))
    _, accepted, _, _, _ = canonical_export_boundary(parsed, home, away)
    internal, _, _ = capture_packet(capture)
    header = parse_packet_text(internal).header
    package = llm_packet(header.get("MATCH", ""), header.get("COMPETITION", ""), header.get("KICKOFF", ""),
                         accepted, READY)
    context = build_context(parse_packet_text(internal))
    return {"home": home, "away": away, "internal": internal, "package": package,
            "context": render_match_context(context), "engine": context}


def setUpModule():
    global A, B
    A, B = products(MATCH_A), products(MATCH_B)


def with_odds(*blocks: str) -> str:
    return MINIMAL.replace("ODDS_COUNT=9;", f"ODDS_COUNT={9 + len(blocks)};") + "".join(blocks)


def odd(**fields) -> str:
    base = dict(CATEGORY="Top", FAMILY="1X2", MARKET="Wynik meczu", PERIOD="FULL_TIME", OWNER="",
                SELECTION="HOME", LINE="", HANDICAP_KIND="", HANDICAP_TAXONOMY="", SETTLEMENT="WIN_LOSE",
                ODDS="2.00", RAW="x 2.00", SOURCE_RAW_RECORD_IDS="run_1:99")
    base.update(fields)
    return "ODD{\n" + "".join(f'{k}="{v}";\n' for k, v in base.items()) + "}\n"


class A_Independence(unittest.TestCase):
    def test_package_and_context_are_different_products(self):
        for match in (A, B):
            package, context = match["package"], match["context"]
            self.assertNotEqual(package, context)
            similarity = difflib.SequenceMatcher(None, package.splitlines(), context.splitlines()).ratio()
            self.assertLess(similarity, 0.05)
            self.assertIn(ODDS_HEADER, package)
            self.assertNotIn(ODDS_HEADER, context)
            self.assertTrue(context.startswith("APEX_MATCH_CONTEXT\n"))
            for section in ("[MARKET_SCRIPT]", "FAIR_1X2=", "EXPECTED_GOALS=", "CENTRAL_SCORES=", "[FAIR_MARKETS]"):
                self.assertIn(section, context)
            self.assertNotIn("[MARKET_SCRIPT]", package)
            for token in JUNK:
                self.assertNotIn(token, package)
                self.assertNotIn(token, context)
            self.assertIn(f"MATCH={match['home']} - {match['away']}", package)
            self.assertIn(f"MATCH={match['home']} - {match['away']}", context)

    def test_context_reports_real_quarantine_and_not_modeled_separately(self):
        # Left-out offers are not mentioned in the context (user request 2026-10-02).
        self.assertNotIn("QUARANTIN", A["context"])
        self.assertNotIn("NOT_MODELED", A["context"])


class GuiWorkflow(unittest.TestCase):
    """B, C, D, E, F: the real Tk buttons and the real Context Engine run."""

    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            cls.root = tk.Tk()
        except tk.TclError:
            raise unittest.SkipTest("no display")
        cls.root.withdraw()
        import gui
        cls.gui = gui
        cls.tmp = tempfile.TemporaryDirectory()
        class InlineThread:
            # Tk only accepts calls from its own thread while mainloop runs; the
            # test pumps events itself, so run the real worker inline.
            def __init__(self, target, args=(), daemon=None):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)

        cls.patches = [patch.object(gui, "BASE_DIR", Path(cls.tmp.name)),
                       patch.object(gui.threading, "Thread", InlineThread),
                       patch.object(gui.messagebox, "showinfo"), patch.object(gui.messagebox, "showwarning"),
                       patch.object(os, "startfile", create=True)]
        for item in cls.patches:
            item.start()
        cls.app = gui.BetclicExtractorGUI(cls.root)

    @classmethod
    def tearDownClass(cls):
        for item in cls.patches:
            item.stop()
        cls.root.destroy()
        cls.tmp.cleanup()

    def load(self, match):
        self.app._on_done({"status": "GOTOWE", "packet_text": match["internal"],
                           "llm_packet_text": match["package"], "odds_count": 1})
        self.root.update()

    def clipboard(self) -> str:
        return self.root.clipboard_get()

    def copy_package(self) -> str:
        self.app.btn_copy.invoke()
        return self.clipboard()

    def copy_context(self) -> str:
        self.app.btn_context.invoke()
        deadline = time.time() + 120
        while self.app.context_is_running and time.time() < deadline:
            self.root.update()
            time.sleep(0.05)
        self.assertFalse(self.app.context_is_running, "context build did not finish")
        return self.clipboard()

    def test_b_c_d_buttons_deliver_their_own_generator_output(self):
        self.load(A)
        package = self.copy_package()
        self.assertEqual(package.strip(), A["package"].strip())                  # B
        context = self.copy_context()
        self.assertEqual(context.strip(), A["context"].strip())                  # C
        self.assertNotEqual(package.strip(), context.strip())                    # D
        self.assertEqual(self.app.current_match_context.strip(), A["context"].strip())
        self.assertEqual(self.app.current_odds_package, A["package"])
        # D: the context button never reads the package source.
        self.app.current_odds_package = "SENTINEL_PACKAGE"
        self.assertNotIn("SENTINEL_PACKAGE", self.copy_context())
        self.load(A)

    def test_e_two_matches_have_no_state_leakage(self):
        self.load(A)
        package_a, context_a = self.copy_package(), self.copy_context()
        self.load(B)
        self.assertEqual(self.app.current_match_context, "")
        package_b, context_b = self.copy_package(), self.copy_context()
        self.assertEqual(package_b.strip(), B["package"].strip())
        self.assertEqual(context_b.strip(), B["context"].strip())
        self.assertNotEqual(package_b, context_b)
        for text in (package_b, context_b):
            self.assertNotIn(A["home"], text)
            self.assertNotIn(A["away"], text)
        self.assertNotEqual(package_a, package_b)
        self.assertNotEqual(context_a, context_b)

    def test_e_late_context_of_previous_match_is_discarded(self):
        self.load(A)
        with tempfile.TemporaryDirectory() as tmp:
            engine = build_context(parse_packet_text(A["internal"]))
            json_path, text_path = write_outputs(engine, tmp)
            self.load(B)
            self.root.clipboard_clear()
            self.root.clipboard_append("B_PACKAGE_ON_CLIPBOARD")
            self.app._on_context_done(self.gui.ContextRunResult(engine.status, json_path, text_path, ""),
                                      A["internal"])
        self.assertEqual(self.clipboard(), "B_PACKAGE_ON_CLIPBOARD")
        self.assertEqual(self.app.current_match_context, "")

    def test_f_repeated_extraction_is_stable(self):
        again = products(MATCH_A)
        self.assertEqual(again["package"], A["package"])
        self.assertEqual(again["context"], A["context"])
        self.load(A)
        first = (self.copy_package(), self.copy_context())
        self.load(A)
        self.assertEqual((self.copy_package(), self.copy_context()), first)


def _record(**fields) -> OddRecord:
    base = dict(category="Strzelcy", family="GOALSCORER", market="Zawodnik strzeli gola nogą", period="FULL_TIME",
                owner="Barcelona", selection="Raphinha", line="", handicap_kind="", handicap_taxonomy="",
                settlement="WIN_LOSE", odds=2.25, raw="Raphinha 2.25", scorer_scope="ANYTIME", participant="Raphinha",
                source_index=1, market_instance="tab:Strzelcy|m", source_raw_record_ids=("run:1",),
                event_teams=("Elche", "Barcelona"))
    base.update(fields)
    return OddRecord(**base)


def _parse(title, selection, raw, home="Juventude RS", away="Avai", native=None, category="Wynik"):
    record, _ = parse_market_record(category=category, market_title=title, raw_selection=selection,
                                    odds_str=raw.split()[-1], raw_text=raw, section_title="", home_team=home,
                                    away_team=away, container_id="c", native_team_names=native)
    return record


def _native():
    html = (ROOT / "snapshots/tab_run_1785272483_10292_2_Wynik.html").read_text(encoding="utf-8")
    return extract_native_team_names(html, "Juventude RS", "Avai")


class G_FalseQuarantineRegression(unittest.TestCase):
    def test_double_chance_with_native_short_team_names_is_canonical(self):
        for selection, expected in (("Juventude lub Avai", "12"), ("Juventude lub remis", "1X"), ("Remis lub Avai", "X2")):
            record = _parse("Podwójna Szansa", selection, f"{selection} 1.27", native=_native())
            self.assertEqual((record["SELECTION"], _semantic_quarantine_reason(record)), (expected, ""))

    def test_corner_totals_including_extra_time_are_totals_not_quarantine(self):
        for title, selection in (("Rzuty rożne NK Celje (razem z dogrywką)", "Powyżej 4,5"),
                                 ("Suma rzutów rożnych (razem z dogrywką)", "Poniżej 7,5")):
            record = _parse(title, selection, f"{selection} 1.38", "NK Celje", "KF Egnatia Rrogozhine",
                            category="Statystyki")
            self.assertEqual((record["FAMILY"], record["PERIOD"], record["LINE"], record["SETTLEMENT"]),
                             ("EVENT_TOTAL", "OTHER", selection.split()[-1].replace(",", "."), "NO_PUSH"))
            self.assertEqual(_semantic_quarantine_reason(record), "")

    def test_one_word_player_names_pass_scorer_safety(self):
        for name in ("Raphinha", "Rodri", "Gavi", "Pedri"):
            self.assertEqual(semantic_safety_quarantine([_record(selection=name, participant=name, raw=f"{name} 2.25")]), [])

    def test_scorer_assister_pair_contract_passes_safety(self):
        record = _record(family="PLAYER_COMBINATION", selection="SCORER_AND_ASSISTER", participant="", scorer_scope="",
                         market="Strzelec bramki i zawodnik, który zaliczy przy niej asystę (czas reg.)",
                         raw="Raphinha (G) i L. Yamal (A) 5.90", odds=5.9)
        self.assertEqual(semantic_safety_quarantine([record]), [])

    def test_proven_non_regular_period_is_not_modeled_not_quarantine(self):
        context = build_context(parse_packet_text(with_odds(
            odd(MARKET="Seria rzutów karnych - zwycięzca", PERIOD="OTHER", RAW="Home FC 1.90", ODDS="1.90"),
            odd(FAMILY="QUALIFICATION_WINNER", MARKET="Zwycięzca rywalizacji", PERIOD="QUALIFICATION",
                RAW="Home FC 1.40", ODDS="1.40"))))
        self.assertEqual(context.status, "PASS")
        self.assertEqual(context.quarantined_rows, [])
        self.assertEqual(len(context.not_modeled_rows), 2)
        rows = quarantine_diagnostics(context)
        self.assertEqual({(r["disposition"], r["quarantine"]) for r in rows}, {("NOT_MODELED", False)})


class H_RealQuarantine(unittest.TestCase):
    def test_extractor_keeps_real_ambiguity_quarantined(self):
        cases = {
            ("Strzelec - Xtra Wygrana", "Lamine Yamal", "Strzelcy"): "UNCONFIRMED_XTRA_PAYOUT_CONTRACT",
            ("Liczba fauli zawodnika (Supersub)", "Gavi Powyżej 1,5", "SuperSub"): "UNCONFIRMED_PLAYER_PROP_PERIOD",
            ("Hat-trick", "Tak", "Strzelcy"): "UNCONFIRMED_MARKET_PERIOD",
        }
        for (title, selection, category), reason in cases.items():
            record = _parse(title, selection, f"{selection} 3.00", "Elche", "Barcelona", category=category)
            self.assertEqual(_semantic_quarantine_reason(record), reason, title)

    def test_audited_undocumented_statistic_periods_stay_closed(self):
        # Earlier audits kept these without period proof (see their own
        # regression tests); the named player/team shots contract is covered.
        for title in ("Liczba fauli zawodnika (OPTA)", "Liczba spalonych zawodnika (OPTA)",
                      "Liczba fauli zawodnika (Supersub)"):
            self.assertEqual(classify_period_detail(title, "", family="PLAYER_PROP")[0], "UNKNOWN")
        self.assertEqual(classify_period_detail("Liczba strzałów zawodnika (OPTA)", "", family="PLAYER_PROP")[0],
                         "MATCH_INCLUDING_EXTRA_TIME")
        for title, selection in (("Dokładna liczba kartek - Avai", "2"), ("Punkty za kartki Powyżej/Poniżej", "Powyżej 45,5")):
            record = _parse(title, selection, f"{selection} 2.10", category="Statystyki")
            self.assertEqual((record["PERIOD"], _semantic_quarantine_reason(record)),
                             ("UNKNOWN", "UNSUPPORTED_OPTIONAL_STATISTICS_PERIOD"))

    def test_double_chance_without_name_evidence_is_quarantined(self):
        context = build_context(parse_packet_text(with_odds(
            odd(FAMILY="DOUBLE_CHANCE", MARKET="Podwójna szansa", SELECTION="Hme lub Awy", RAW="Hme lub Awy 1.30"))))
        self.assertEqual(context.status, "PASS_WITH_QUARANTINE")
        self.assertEqual(context.quarantined_rows[0]["reasons"], ["AMBIGUOUS_COMPOUND_OUTCOME"])

    def test_non_player_and_team_selections_fail_scorer_safety(self):
        for selection in ("Tak", "Remis", "Barcelona", "Nikt"):
            rows = semantic_safety_quarantine([_record(selection=selection, participant=selection,
                                                       raw=f"{selection} 2.25")])
            self.assertEqual([row["reason"] for row in rows], ["SCORER_PLAYER_IDENTITY_MISSING"], selection)
        rows = semantic_safety_quarantine([_record(participant="")])
        self.assertEqual([row["reason"] for row in rows], ["SCORER_PLAYER_IDENTITY_MISSING"])

    def test_every_quarantine_is_explained(self):
        context = build_context(parse_packet_text(with_odds(
            odd(ODDS="abc", RAW="x abc", SOURCE_RAW_RECORD_IDS="run_7:42"),
            odd(FAMILY="DOUBLE_CHANCE", MARKET="Podwójna szansa", SELECTION="Hme lub Awy", RAW="Hme lub Awy 1.30"),
        ) + '\nSEMANTIC_QUARANTINE{\nMARKET="Strzelec - Xtra Wygrana";\nPERIOD="UNKNOWN";\n'
            'REASON="UNCONFIRMED_XTRA_PAYOUT_CONTRACT";\nRAW_RECORD_ID="run_7:43";\n}\n'))
        self.assertEqual(context.status, "PASS_WITH_QUARANTINE")
        rows = quarantine_diagnostics(context)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertTrue(row["quarantine"])
            for key in ("record_id", "market_name", "reason_code", "reason_details", "source_stage"):
                self.assertTrue(row[key], (key, row))
        by_code = {row["reason_code"].split(":")[0]: row for row in rows}
        self.assertEqual(by_code["INVALID_NUMBER"]["record_id"], "run_7:42")
        self.assertEqual(by_code["INVALID_NUMBER"]["source_stage"], "PACKET_VALIDATION")
        self.assertEqual(by_code["UNCONFIRMED_XTRA_PAYOUT_CONTRACT"]["source_stage"], "EXTRACTOR_SEMANTIC")
        self.assertEqual(by_code["UNCONFIRMED_XTRA_PAYOUT_CONTRACT"]["record_id"], "run_7:43")
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(context, tmp)
            saved = json.loads((Path(tmp) / "APEX_QUARANTINE_DIAGNOSTICS.json").read_text(encoding="utf-8"))
            report = (Path(tmp) / "APEX_CONTEXT_REPORT.txt").read_text(encoding="utf-8")
        self.assertEqual(saved, json.loads(json.dumps(rows)))
        self.assertNotIn("run_7:42", report)  # explanations stay internal


class ReleaseSelfTestProductChecks(unittest.TestCase):
    def test_live_self_test_proves_distinct_clean_products(self):
        from release_self_test import _product_checks
        with tempfile.TemporaryDirectory() as tmp:
            engine = build_context(parse_packet_text(A["internal"]))
            _, text_path = write_outputs(engine, tmp)
            good = _product_checks(A["package"], text_path, Path(tmp))
            text_path.write_text(A["package"], encoding="utf-8")        # the old regression
            same = _product_checks(A["package"], text_path, Path(tmp))
        self.assertTrue(good["products_distinct"] and good["products_clean"] and good["quarantine_explained"])
        self.assertIn("QUARANTINE:EXTRACTOR_SEMANTIC:UNCONFIRMED_XTRA_PAYOUT_CONTRACT", good["quarantine_summary"])
        self.assertFalse(same["products_distinct"])


class BrowserSnapshotEndToEnd(unittest.TestCase):
    """Playwright/Chromium over real saved Betclic pages -> both products."""

    RUNS = {"1787475817_15748": ("Elche", "Barcelona"), "1785272483_10292": ("Juventude RS", "Avai"),
            "1785259772_7560": ("NK Celje", "KF Egnatia Rrogozhine")}
    FALSE_POSITIVE_CODES = {"AMBIGUOUS_COMPOUND_OUTCOME", "SCORER_PLAYER_IDENTITY_MISSING", "AMBIGUOUS_GOALSCORER_SCOPE",
                            "UNCONFIRMED_MARKET_SETTLEMENT"}

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from core import _extract_dom_from_page
        cls.results = {}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())
            for run, (home, away) in cls.RUNS.items():
                files = sorted((ROOT / "snapshots").glob(f"tab_run_{run}_*.html"))
                wynik = next(f for f in files if f.name.endswith("_Wynik.html"))
                native = extract_native_team_names(wynik.read_text(encoding="utf-8"), home, away)
                parsed, raw_rows = [], 0
                for path in files:
                    tab = re.fullmatch(r"tab_run_\d+_\d+_\d+_(.+)\.html", path.name).group(1).replace("Dok_adny_wynik", "Dokładny wynik")
                    page.set_content(path.read_text(encoding="utf-8", errors="replace"), wait_until="domcontentloaded")
                    for index, item in enumerate(_extract_dom_from_page(page, tab)):
                        raw_rows += 1
                        if not item["market"]:
                            continue
                        record, _ = parse_market_record(
                            category=tab, market_title=item["market"], raw_selection=item["selection"],
                            odds_str=item["odds"], raw_text=item["raw"], section_title=item["section_title"],
                            ancestor_title=item["ancestor_title"], period_hint=item["period_hint"], main_tab=tab,
                            settlement_scope_hint=item["settlement_scope_hint"], line_hint=item["line_hint"],
                            participant_hint=item["participant_hint"], handicap_kind_hint=item["handicap_kind"],
                            market_instance_id=item["market_instance_id"], home_team=home, away_team=away,
                            container_id=item["container_id"], native_team_names=native or None,
                            raw_record_id=f"{run}:{path.name}:{index}", source_raw_record_ids=[f"{run}:{path.name}:{index}"])
                        if record:
                            record["source_index"] = len(parsed) + 1
                            parsed.append(record)
                _, accepted, quarantined, _, _ = canonical_export_boundary(parsed, home, away)
                cls.results[run] = (home, away, raw_rows, accepted, quarantined)
            browser.close()

    def _context(self, home, away, accepted, quarantined):
        from core import semantic_quarantine_ledger
        block = lambda name, fields: name + "{\n" + "".join(f'{k}="{v}";\n' for k, v in fields.items()) + "}\n"
        text = block("BETCLIC_FULL_ODDS_PACKET", dict(MATCH=f"{home} - {away}", COMPETITION="Snapshot", KICKOFF="",
                     PARSER_TRUTH_STATUS="PASS", ANALYSIS_READY="YES", CLEAN_CORE_READY="YES", FULL_USABLE_READY="YES",
                     ODDS_COUNT=len(accepted), UNRESOLVED_COUNT=0, COMPLETENESS_SCORE=100.0))
        keys = ("CATEGORY FAMILY MARKET PERIOD OWNER SELECTION LINE HANDICAP_KIND HANDICAP_TAXONOMY SETTLEMENT ODDS RAW "
                "PERIOD_SOURCE PERIOD_CONFIDENCE SCORER_SCOPE PARTICIPANT MARKET_INSTANCE_ID").split()
        for row in accepted:
            fields = {k: row.get(k, "") for k in keys}
            fields["SOURCE_RAW_RECORD_IDS"] = ",".join(row.get("source_raw_record_ids") or [])
            text += block("ODD", fields)
        for row in semantic_quarantine_ledger(quarantined):
            text += block("SEMANTIC_QUARANTINE", {k.upper(): v for k, v in row.items() if not isinstance(v, list)})
        return build_context(parse_packet_text(text))

    def test_real_pages_produce_two_products_without_false_quarantine(self):
        for run, (home, away, raw_rows, accepted, quarantined) in self.results.items():
            with self.subTest(match=f"{home} - {away}"):
                self.assertGreater(len(accepted), 400)
                context = self._context(home, away, accepted, quarantined)
                self.assertNotEqual(context.status, "BLOCKED")
                package = llm_packet(f"{home} - {away}", "Snapshot", "", accepted, READY)
                text = render_match_context(context)
                self.assertNotEqual(package, text)
                self.assertIn(ODDS_HEADER, package)
                self.assertTrue(text.startswith("APEX_MATCH_CONTEXT"))
                self.assertNotIn("betting-slip", package + text)
                codes = {row["reason_code"] for row in quarantine_diagnostics(context) if row["quarantine"]}
                self.assertFalse(codes & self.FALSE_POSITIVE_CODES, codes)
                for row in quarantine_diagnostics(context):
                    self.assertTrue(row["reason_code"] and row["source_stage"] and row["record_id"])

    def test_real_quarantine_still_fires_on_real_pages(self):
        home, away, _, accepted, quarantined = self.results["1787475817_15748"]
        reasons = {_semantic_quarantine_reason(row) for row in quarantined}
        self.assertIn("UNCONFIRMED_XTRA_PAYOUT_CONTRACT", reasons)
        self.assertIn("UNCONFIRMED_MARKET_PERIOD", reasons)       # Hat-trick, "Gole": no stated period
        self.assertIn("UNCONFIRMED_PLAYER_PROP_PERIOD", reasons)  # SuperSub statistics


if __name__ == "__main__":
    unittest.main()
