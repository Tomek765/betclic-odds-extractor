from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from diagnostics import (
    DIAGNOSTICS_DIR,
    LOGS_DIR,
    PROFILE_DIR,
    SNAPSHOTS_DIR,
    DiagnosticsManager,
)
from apex_context_engine.llm_format import render_llm_odds
from exhaustive import ExhaustiveStateCrawler
from history_contract_v0_1 import (
    build_history_observation,
    canonicalize_utc_datetime,
    evaluate_capture_status,
    extract_embedded_provider_match_info,
    parse_betclic_route_event_id,
    utc_now_rfc3339,
    write_history_sidecars,
)
from snapshot_manifest_v0_1 import build_and_write_manifest
from identity_bridge_v0_1 import (
    IdentityBridgeValidationError,
    build_provider_derived_bridge,
    load_exact_persisted_bridge,
    write_bridge_append_only,
)
from provider_transport_v0_1 import PassiveBetclicTransportListener, format_transport_exception
from parser import (
    classify_family,
    classify_period,
    classify_period_detail,
    clean_team_name,
    has_selectable_time_window,
    is_fast_window_tab,
    is_correct_score_group_selection,
    headerless_top_card_exclusion,
    neutralize_unrecognized_top_card,
    parse_market_record,
    recover_headerless_top_offer,
    _known_not_modeled_settlement,
)

BUILD_ID = "APEX_CONTEXT_ENGINE_FIXED_20261002_FAST7"
# Monotonic release order (UTC yyyymmddHHMM).  version_guard and the
# installer compare it with BUILD_INFO.txt BUILD_SEQ / BUILT_AT of older builds.
BUILD_SEQ = 202610022330
ACCOUNTING_SCHEMA_VERSION = "2.0"
SEMANTIC_QUARANTINE_SCHEMA_VERSION = "2.0"
DEFAULT_TAB_MAX_SECONDS = 60.0
DEFAULT_RUN_MAX_SECONDS = 600.0
PROVIDER_TRANSPORT_DRAIN_MS = 2000
HISTORY_V0_1_DIR = DIAGNOSTICS_DIR / "history_v0_1"
HISTORY_SNAPSHOT_MANIFEST_V0_1_DIR = HISTORY_V0_1_DIR / "manifests"
HISTORY_IDENTITY_BRIDGE_V0_1_DIR = HISTORY_V0_1_DIR / "identity_bridges"
HISTORY_PROVIDER_TRANSPORT_V0_1_DIR = HISTORY_V0_1_DIR / "provider_transport"
CLEAN_CORE_FAMILIES = frozenset({
    "1X2", "DOUBLE_CHANCE", "BTTS", "GOALS_OU", "TEAM_TOTALS_HOME",
    "TEAM_TOTALS_AWAY", "HANDICAP_EUROPEAN", "CORRECT_SCORE", "CORRECT_SCORE_GROUP",
})
PLAYER_PROP_FAMILIES = frozenset({"PLAYER_PROP", "PLAYER_PROP_XTRA", "GOALSCORER", "PLAYER_COMBINATION"})
KNOWN_VALID_NOT_MODELED_FAMILIES = frozenset({
    "GOAL_PARITY", "CLEAN_SHEET", "TEAM_WIN_TO_NIL", "EXACT_GOALS", "GOAL_RANGE",
    "HIGHER_SCORING_HALF", "GOAL_MARGIN", "TEAM_SCORES_BOTH_HALVES",
    "TEAM_WINS_ONE_HALF", "TEAM_WINS_BOTH_HALVES", "FIRST_GOAL_TIME",
    "QUALIFICATION_WINNER", "QUALIFICATION_METHOD", "BINARY_EVENT",
    "EVENT_FIRST_LAST", "EVENT_RANGE", "EVENT_PARITY", "EVENT_EXACT", "EVENT_RESULT",
})


def log_provider_transport_listener_errors(diag: DiagnosticsManager, listener: Any | None) -> None:
    """Persist already-redacted passive-listener failures before terminal return."""
    if listener is None:
        return
    for listener_error in listener.errors:
        diag.log(f"HISTORY_PROVIDER_TRANSPORT_V0_1_LISTENER_ERROR:{listener_error}")


def log_provider_transport_flush_summary(diag: DiagnosticsManager, listener: Any | None) -> None:
    """Make target-response decisions visible in the run log after flush."""
    summary = getattr(listener, "last_flush_summary", None) if listener is not None else None
    if summary:
        diag.log("HISTORY_PROVIDER_TRANSPORT_V0_1_RECEIPT_SUMMARY=" + json.dumps(
            summary, sort_keys=True, separators=(",", ":"),
        ))



def validate_betclic_url(url: str) -> tuple[bool, str]:
    cleaned = url.strip()
    if not cleaned:
        return False, "URL nie może być pusty."
    if cleaned.startswith("file://"):
        return True, ""
    if not cleaned.startswith(("http://", "https://")):
        return False, "Niepoprawny protokół. URL musi zaczynać się od http://, https:// lub file://"
    if "betclic." not in cleaned.lower():
        return False, "Podany URL nie należy do domeny Betclic."
    return True, ""


# Why a capture was refused before any odds were read (pre-match odds only).
_EVENT_STATUS_MESSAGES = {
    "LIVE": "Mecz już trwa (na żywo) - program pobiera tylko kursy PRZED meczem. Wybierz mecz, który się jeszcze nie zaczął.",
    "FT": "Mecz jest zakończony - program pobiera tylko kursy PRZED meczem.",
    "POSTPONED": "Mecz jest przełożony - Betclic nie prowadzi dla niego normalnej oferty przedmeczowej.",
    "UNKNOWN": "Nie rozpoznano strony meczu. Wklej link do konkretnego meczu (strona wydarzenia, nie lista meczów).",
}

_RUNTIME_ERROR_HINTS = (
    (("processsingleton", "user data directory is already in use", "singletonlock"),
     "BROWSER_PROFILE_IN_USE",
     "Przeglądarka programu jest już używana (drugie okno APEX albo niezakończone pobieranie). "
     "Zamknij inne okna programu i spróbuj ponownie."),
    (("target page, context or browser has been closed", "browser has been closed", "targetclosederror",
      "browser closed"),
     "BROWSER_CLOSED",
     "Okno przeglądarki zostało zamknięte w trakcie pobierania. Uruchom pobieranie ponownie "
     "i nie zamykaj okna przeglądarki do końca."),
    (("executable doesn't exist", "executable doesn\u2019t exist", "failed to launch"),
     "BROWSER_MISSING",
     "Nie udało się uruchomić przeglądarki programu. Zainstaluj ponownie najnowszą paczkę."),
    (("net::err_", "name_not_resolved", "internet_disconnected", "connection_refused"),
     "NETWORK_ERROR",
     "Brak połączenia z Betclic. Sprawdź internet i spróbuj ponownie."),
)


def _is_bet_builder_tab(name: str) -> bool:
    """Betclic's MyCombi bet-builder tab (no standalone market odds)."""
    return str(name or "").strip().casefold() == "mycombi"


def _friendly_runtime_error(exc: BaseException) -> tuple[str, str]:
    """Map common environment failures to a clear Polish message; keep the raw text."""
    raw = f"{type(exc).__name__}: {exc}"
    lowered = raw.casefold()
    for needles, code, message in _RUNTIME_ERROR_HINTS:
        if any(needle in lowered for needle in needles):
            return code, f"{message} (szczegóły: {raw[:200]})"
    return "UNHANDLED_EXCEPTION", f"Błąd wykonania: {exc}"


def _detect_live_event_status(page: Any) -> tuple[bool, str]:
    """
    Detects if the page represents a live ongoing event.
    Returns (is_live, live_signal_description).
    """
    try:
        res = page.evaluate("""() => {
            const liveSelectors = [
                '.event_header.is-live',
                '.cardEvent.is-live',
                '.has-liveScoreboard',
                'scoreboards-timer',
                '.is-live'
            ];
            for (const sel of liveSelectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    return { is_live: true, signal: sel, text: txt.slice(0, 50) };
                }
            }

            const classElements = Array.from(document.querySelectorAll('[class*="is-live"], [class*="isLive"]'));
            if (classElements.length > 0) {
                return { is_live: true, signal: 'class_is_live', text: '' };
            }

            const timerEl = document.querySelector('scoreboards-timer, .event_infoTime, [class*="timer"]');
            if (timerEl) {
                const txt = (timerEl.innerText || timerEl.textContent || '').trim();
                if (txt && (/\\d{1,2}['\\u2019]|min|po?owa|halftime/i.test(txt))) {
                    return { is_live: true, signal: 'timer_text', text: txt.slice(0, 50) };
                }
            }

            return { is_live: false, signal: '', text: '' };
        }""")
        return bool(res.get("is_live")), str(res.get("signal") or "")
    except Exception:
        return False, ""


def _preflight_event_status(page: Any) -> tuple[str, str, float]:
    """Classify event state before tab traversal or any odds capture."""
    started = time.time()
    try:
        result = page.evaluate("""() => {
            const text = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
            const liveSelectors = ['.event_header.is-live', '.cardEvent.is-live', '.has-liveScoreboard', 'scoreboards-timer', '.is-live'];
            for (const selector of liveSelectors) { const el=document.querySelector(selector); if(el) return {status:'LIVE', proof:selector+':'+text(el).slice(0,120)}; }
            const body = text(document.body).toLowerCase();
            if (/postponed|prze[oł]oż/.test(body)) return {status:'POSTPONED', proof:'page_text'};
            if (/final whistle|mecz zakończony|wynik końcowy|\bft\b/.test(body)) return {status:'FT', proof:'page_text'};
            const header = document.querySelector('.event_header, .scoreboard, [class*=eventHeader], [class*=event_header]');
            if (header) return {status:'PREMATCH', proof:'event_header_no_live:'+text(header).slice(0,120)};
            return {status:'UNKNOWN', proof:'NO_EVENT_HEADER'};
        }""")
        if isinstance(result, dict):
            status = str(result.get("status") or "").upper()
            if status in {"PREMATCH", "LIVE", "FT", "POSTPONED", "UNKNOWN"}:
                return status, str(result.get("proof") or ""), round(time.time() - started, 3)
            # Compatibility with existing test doubles for live detection.
            if "is_live" in result:
                return ("LIVE" if result.get("is_live") else "PREMATCH"), str(result.get("signal") or ""), round(time.time() - started, 3)
    except Exception as exc:
        return "UNKNOWN", f"PREFLIGHT_EXCEPTION:{type(exc).__name__}", round(time.time() - started, 3)
    return "UNKNOWN", "PREFLIGHT_INVALID_RESULT", round(time.time() - started, 3)


def _get_dom_expansion_metrics(page: Any, tab_name: str = "") -> dict[str, int]:
    try:
        # Keep this as a no-argument browser evaluation.  Apart from being simpler
        # for Playwright, it preserves the established capture fixture contract.
        # JSON encoding keeps the tab value safe when embedded in the script.
        tab_literal = json.dumps(str(tab_name), ensure_ascii=False)
        script = """(() => {
            const tabName = __APEX_TAB_NAME__;
            const isMyCombi = String(tabName || '').trim().toLowerCase() === 'mycombi';
            const scope = isMyCombi
                ? document.querySelector('sports-betting-slip')
                : document.querySelector('.marketBox_container.is-active');
            // Fixture/minimal DOMs do not mount the production panel shell;
            // only in that absence retain the historical document fallback.
            const rawElements = Array.from((scope || document).querySelectorAll('button.is-odd, button[class*="odd"], [class*="oddValue"]')).filter(rawEl => {
                const btn = rawEl.closest('button') || rawEl;
                const card = btn.closest('sports-top-my-combi');
                return !card || Boolean(card.querySelector('.marketBox_headTitle, .marketBox_head, .market_header, h2, h3, h4'));
            });
            const seenButtons = new Set();
            let interactive = 0;
            let priced = 0;
            let unpriced = 0;

            for (const rawEl of rawElements) {
                const btn = rawEl.closest('button') || rawEl;
                if (seenButtons.has(btn)) continue;
                seenButtons.add(btn);
                if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') continue;

                interactive++;
                const oddsEl = btn.querySelector('.oddValue, [class*="oddValue"], .is-oddValue') || btn;
                const txt = (oddsEl.innerText || oddsEl.textContent || '').replace(/\\n+/g, ' ').trim();
                const m = txt.match(/([1-9]\\d{0,2}(?:[.,]\\d{1,2})?)/);
                if (m && parseFloat(m[1].replace(',', '.')) > 1.00) {
                    priced++;
                } else {
                    unpriced++;
                }
            }

            const rem_closed = document.querySelectorAll('button[aria-expanded="false"], .marketBox_header.is-closed').length;
            const rem_more = Array.from(document.querySelectorAll('button, span')).filter(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                return t === 'Pokaż więcej' || t === 'Więcej';
            }).length;

            return {
                interactive_control_count: interactive,
                priced_candidate_count: priced,
                unpriced_control_count: unpriced,
                selectable_count: interactive,
                remaining_closed: rem_closed,
                remaining_more: rem_more
            };
        })()""".replace("__APEX_TAB_NAME__", tab_literal)
        metrics = page.evaluate(script)
        return metrics
    except Exception:
        return {
            "interactive_control_count": 0,
            "priced_candidate_count": 0,
            "unpriced_control_count": 0,
            "selectable_count": 0,
            "remaining_closed": 0,
            "remaining_more": 0
        }


def _retry_unfinished_strzelcy_containers(page: Any, activate_tab: Callable[[], None], log: Callable[[str], None]) -> list[dict[str, Any]]:
    """Bounded, locator-based retry for virtual scorer lists; never reuses DOM handles."""
    retries: list[dict[str, Any]] = []
    for retry in range(1, 4):
        activate_tab()
        metrics = page.evaluate("""() => Array.from(document.querySelectorAll('[class*=scroller], [class*=scroll]')).map((el,i)=>({locator:el.tagName+'.'+el.className+'#'+i,height:el.scrollHeight,top:el.scrollTop,priced:el.querySelectorAll('button.is-odd').length,last:(Array.from(el.querySelectorAll('button.is-odd')).pop()||{}).innerText||''})).filter(x=>x.height>x.top+1)""")
        for metric in metrics:
            stable = 0; previous = None
            for _ in range(60):
                state = page.evaluate("""locator => { const els=Array.from(document.querySelectorAll('[class*=scroller], [class*=scroll]')); const el=els.find((x,i)=>x.tagName+'.'+x.className+'#'+i===locator); if(!el)return null; el.scrollTop=el.scrollHeight; const odds=Array.from(el.querySelectorAll('button.is-odd')); return {height:el.scrollHeight,priced:odds.length,last:(odds.pop()||{}).innerText||''}; }""", metric["locator"])
                if state is None: break
                stable = stable + 1 if state == previous else 0
                previous = state
                if stable >= 3: break
                time.sleep(0.05)
            retries.append({"retry": retry, "locator": metric["locator"], "state": previous, "finished": stable >= 3})
            log(f"STRZELCY_SCROLL_RETRY retry={retry} locator={metric['locator']} stable={stable >= 3} state={previous}")
        if retries and all(item["finished"] for item in retries if item["retry"] == retry): break
    return retries


def _evaluate_tab_status(metrics: dict[str, Any]) -> tuple[str, str]:
    activation_ok = metrics.get("activation_ok", True)
    exc = metrics.get("exception")
    priced = metrics.get("priced_candidate_count", 0)
    unpriced = metrics.get("unpriced_control_count", 0)
    raw = metrics.get("raw_dom_items", 0)
    parsed = metrics.get("parsed_odds_count", 0)
    unresolved = metrics.get("unresolved_count", 0)
    closed = metrics.get("remaining_closed", 0)
    more = metrics.get("remaining_more", 0)
    deadline = metrics.get("deadline_hit", False)
    accounted_rejected = int(metrics.get("accounted_rejected_count", 0) or 0)
    foreign_rejected = int(metrics.get("foreign_rejected_count", 0) or 0)
    unaccounted_value = metrics.get("unaccounted_priced_count")
    unaccounted_priced = int(unaccounted_value or 0)

    if not activation_ok:
        return "FAIL", "TAB_ACTIVATION_FAILED"

    if exc:
        return "FAIL", f"TAB_EXCEPTION_{exc}"

    if unaccounted_value is not None and priced > 0 and unaccounted_priced > 0:
        return "FAIL", "UNACCOUNTED_PRICED_CANDIDATES"

    if priced > 0 and raw == 0 and accounted_rejected >= priced:
        if foreign_rejected >= priced:
            return "PASS", "ALL_PRICED_CANDIDATES_ACCOUNTED_FOREIGN"
        return "PASS", "ALL_PRICED_CANDIDATES_ACCOUNTED_AND_REJECTED"

    if priced > 0 and raw == 0:
        return "FAIL", "ZERO_RAW_WITH_PRICED_CANDIDATES"

    if deadline:
        return "PARTIAL", "DEADLINE_EXCEEDED"

    if closed > 0 or more > 0:
        return "PARTIAL", "UNEXPANDED_ELEMENTS"

    if unresolved > 0 and parsed > 0:
        return "PARTIAL", "HAS_UNRESOLVED"

    if priced == 0 and unpriced > 0 and raw == 0:
        return "PASS", "NO_STANDALONE_ODDS"

    if priced == 0 and unpriced == 0 and raw == 0:
        return "PASS", "EMPTY_TAB"

    # A normal, fully traversed terminal tab must conserve its ledger.  Keep
    # more-specific zero-raw, deadline and expansion diagnostics above it.
    if unaccounted_value is not None and priced != parsed + accounted_rejected + unaccounted_priced:
        return "FAIL", "LEDGER_CONSERVATION_GAP"

    return "PASS", "OK"


def candidate_ledger_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate terminal candidate accounting and derive deterministic summaries."""
    terminal = {"PARSED_CANONICAL", "DUPLICATE_MERGED", "PASSIVE_NON_ODD", "GLOBAL_OVERLAY_ACCOUNTED",
                "ACCOUNTED_EXCLUDED_WITH_REASON", "FOREIGN", "FOREIGN_EVENT_REJECTED", "UNACCOUNTED_FAILURE"}
    by_id: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    for entry in entries:
        fingerprint = "|".join(str(entry.get(key) or "") for key in ("run_id", "event_id", "source_hash", "tab", "container_id", "row_id", "column_id", "native_selection_id"))
        candidate_id = str(entry.get("candidate_id") or "cand_" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24])
        state = str(entry.get("terminal_state") or "UNACCOUNTED_FAILURE")
        if state not in terminal: state = "UNACCOUNTED_FAILURE"
        normalized = {**entry, "candidate_id": candidate_id, "terminal_state": state}
        if candidate_id in by_id and by_id[candidate_id]["terminal_state"] != state: conflicts.append(candidate_id)
        else: by_id[candidate_id] = normalized
    rows = list(by_id.values())
    by_tab: dict[str, dict[str, int]] = {}
    for row in rows:
        summary = by_tab.setdefault(str(row.get("tab") or ""), {"priced":0,"parsed":0,"accounted_rejected":0,"foreign_rejected":0,"unaccounted":0})
        summary["priced"] += 1
        if row["terminal_state"] in {"PARSED_CANONICAL","DUPLICATE_MERGED"}: summary["parsed"] += 1
        elif row["terminal_state"] != "UNACCOUNTED_FAILURE":
            summary["accounted_rejected"] += 1
            if row["terminal_state"] in {"FOREIGN", "FOREIGN_EVENT_REJECTED"}:
                summary["foreign_rejected"] += 1
        else: summary["unaccounted"] += 1
    return {"entries": rows, "by_tab": by_tab, "unaccounted": sum(x["unaccounted"] for x in by_tab.values()), "conflicts": sorted(set(conflicts))}


def _safe_tab_name(tab_name: str, index: int) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "_", tab_name).strip("_")
    return cleaned if cleaned else f"TAB_{index}"


def dismiss_known_betclic_overlays(page: Any, log: Callable[[str], None] | None = None) -> int:
    """Close only recognized Betclic onboarding/promotional modal dialogs."""
    selectors = (
        "sports-extra-win-onboarding-modal button:has-text('Zamknij')",
        ".cdk-overlay-container mat-dialog-container button:has-text('Zamknij')",
        ".cdk-overlay-container mat-dialog-container button:has-text('Close')",
    )
    dismissed = 0
    for selector in selectors:
        try:
            button = page.query_selector(selector)
            if not button or not button.is_visible():
                continue
            try:
                button.click(timeout=3000)
            except Exception:
                # The target is still the allow-listed close button; only the
                # Playwright actionability check is bypassed by this fallback.
                button.evaluate("el => el.click()")
            dismissed += 1
            if log:
                log(f"BETCLIC_MODAL_DISMISSED selector={selector}")
            time.sleep(0.25)
        except Exception as exc:
            if log:
                log(f"BETCLIC_MODAL_DISMISS_FAILED selector={selector}: {exc}")
    return dismissed


def _export_raw_jsonl(records: list[dict[str, Any]], filepath: Path) -> tuple[int, str, str]:
    """
    Exports raw pre-deduplication records to JSONL atomically.
    Returns (written_count, sha256_hex, export_status).
    """
    tmp_path = filepath.with_suffix(".tmp")
    try:
        lines = []
        for r in records:
            lines.append(json.dumps(r, ensure_ascii=False))
        tmp_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        os.replace(tmp_path, filepath)

        written_lines = [l for l in filepath.read_text(encoding="utf-8").splitlines() if l.strip()]
        written_count = len(written_lines)

        sha256_hex = hashlib.sha256(filepath.read_bytes()).hexdigest()
        status = "PASS" if written_count == len(records) else "FAIL"
        return written_count, sha256_hex, status
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return 0, "", "FAIL"


def _source_hash_from_capture_sources(sources: dict[str, bytes]) -> str:
    """Return one deterministic SHA-256 for the pre-parser capture payloads."""
    manifest = b"".join(
        name.encode("utf-8") + b"\x00" + hashlib.sha256(sources[name]).hexdigest().encode("ascii") + b"\n"
        for name in sorted(sources)
    )
    return hashlib.sha256(manifest).hexdigest()


def extract_current_event_kickoff(structured_value: str = "", visible_value: str = "") -> tuple[str, str]:
    """Return only current-event, explicitly rendered kickoff evidence.

    No date or timezone is inferred; callers keep the display string as rendered.
    """
    for source, value in (("EVENT_STRUCTURED_DATETIME", structured_value), ("EVENT_HEADER_VISIBLE", visible_value)):
        match = re.search(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)", str(value or ""))
        if match:
            return match.group(0), source
    return "", "KICKOFF_SOURCE_MISSING"


def _propagate_source_hash(raw_records: list[dict[str, Any]], canonical_records: list[dict[str, Any]], source_hash: str) -> None:
    """Transport one capture hash without affecting semantic record identity."""
    for raw_record in raw_records:
        raw_record["source_hash"] = source_hash
        for candidate in raw_record.get("period_evidence_candidates") or []:
            candidate["source_hash"] = source_hash
    for canonical_record in canonical_records:
        canonical_record["source_hash"] = source_hash


def classify_period_evidence(candidate: dict[str, Any]) -> tuple[str, str]:
    """Classify only explicit HF5B scoped labels; unsupported or mixed labels stay UNKNOWN."""
    values = [str(candidate.get(key) or "") for key in ("raw_value", "normalized_hint")]
    text = " ".join(values).lower().replace("ł", "l")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    found: set[str] = set()
    if re.search(r"(?:^|\s)(?:1\.?\s*polowa|pierwsza\s+polowa|first\s+half)(?:$|\s)", text):
        found.add("P1")
    if re.search(r"(?:^|\s)(?:2\.?\s*polowa|druga\s+polowa|second\s+half)(?:$|\s)", text):
        found.add("P2")
    if re.search(r"(?:caly\s+mecz|full\s+match|90\s*(?:min|minut))", text):
        found.add("FT")
    if len(found) == 1:
        return next(iter(found)), "PERIOD_EVIDENCE_EXPLICIT_SCOPE"
    if len(found) > 1:
        return "UNKNOWN", "PERIOD_EVIDENCE_SCOPE_CONFLICT"
    return "UNKNOWN", "PERIOD_EVIDENCE_NO_EXPLICIT_SCOPE"


_EVIDENCE_TO_PERIOD = {"FT": "FULL_TIME", "P1": "1ST_HALF", "P2": "2ND_HALF",
                       "FULL_TIME": "FULL_TIME", "1ST_HALF": "1ST_HALF", "2ND_HALF": "2ND_HALF"}


def resolve_periods_from_lineage(
    canonical_records: list[dict[str, Any]], raw_records: list[dict[str, Any]],
    excluded_lineage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve only UNKNOWN canonical periods from unanimous same-context HF5B evidence."""
    evidence_by_id: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_records:
        for candidate in raw.get("period_evidence_candidates") or []:
            raw_id = str(candidate.get("raw_record_id") or raw.get("raw_record_id") or "")
            if raw_id:
                evidence_by_id.setdefault(raw_id, []).append(candidate)
    canonical_ids = {
        source_id for record in canonical_records
        for source_id in (record.get("source_raw_record_ids") or
                          ([record["raw_record_id"]] if record.get("raw_record_id") else []))
    }
    excluded_ids = {
        source_id for entry in (excluded_lineage or [])
        for source_id in (entry.get("source_raw_record_ids") or
                          ([entry["raw_record_id"]] if entry.get("raw_record_id") else []))
    }
    before = {period: sum(record.get("PERIOD") == period for record in canonical_records)
              for period in ("FULL_TIME", "1ST_HALF", "2ND_HALF", "UNKNOWN")}
    diagnostics: dict[str, Any] = {
        "CANONICAL_TOTAL": len(canonical_records), "BEFORE_FT": before["FULL_TIME"],
        "BEFORE_P1": before["1ST_HALF"], "BEFORE_P2": before["2ND_HALF"],
        "BEFORE_UNKNOWN": before["UNKNOWN"], "ASSIGNED_UNKNOWN_TO_FT": 0,
        "ASSIGNED_UNKNOWN_TO_P1": 0, "ASSIGNED_UNKNOWN_TO_P2": 0,
        "UNCHANGED_EXISTING": 0, "UNKNOWN_NO_EVIDENCE": 0,
        "UNKNOWN_EVIDENCE_CONFLICT": 0, "EXISTING_PERIOD_CONFLICT": 0,
        "FOREIGN_EVIDENCE_REJECTED": 0,
        "EVIDENCE_WITHOUT_CANONICAL": len(set(evidence_by_id) - canonical_ids - excluded_ids),
        "EXCLUDED_LINEAGE_COUNT": len(excluded_lineage or []), "decisions": [],
    }
    for record in canonical_records:
        source_ids = sorted(record.get("source_raw_record_ids") or
                            ([record["raw_record_id"]] if record.get("raw_record_id") else []))
        valid: list[tuple[str, str]] = []
        for source_id in source_ids:
            for candidate in evidence_by_id.get(source_id, []):
                if any(str(candidate.get(field) or "") != str(record.get(field) or "")
                       for field in ("run_id", "event_id", "source_hash")):
                    diagnostics["FOREIGN_EVIDENCE_REJECTED"] += 1
                    continue
                period = _EVIDENCE_TO_PERIOD.get(str(candidate.get("evidence_period") or "").upper())
                if period:
                    valid.append((source_id, period))
        periods = sorted({period for _, period in valid})
        existing = record.get("PERIOD") or "UNKNOWN"
        decision = {"source_raw_record_ids": source_ids, "evidence_ids": sorted({source_id for source_id, _ in valid}),
                    "evidence_periods": periods, "reason_code": ""}
        if existing != "UNKNOWN":
            diagnostics["UNCHANGED_EXISTING"] += 1
            if periods and (len(periods) != 1 or periods[0] != existing):
                diagnostics["EXISTING_PERIOD_CONFLICT"] += 1
                decision["reason_code"] = "PERIOD_EXISTING_CONFLICT"
            else:
                decision["reason_code"] = "PERIOD_EXISTING_PRESERVED"
        elif not periods:
            diagnostics["UNKNOWN_NO_EVIDENCE"] += 1
            decision["reason_code"] = "PERIOD_NO_EVIDENCE"
        elif len(periods) > 1:
            diagnostics["UNKNOWN_EVIDENCE_CONFLICT"] += 1
            decision["reason_code"] = "PERIOD_EVIDENCE_CONFLICT"
        else:
            resolved = periods[0]
            record["PERIOD"] = resolved
            record["PERIOD_SOURCE"] = "HF5B_LINEAGE_EVIDENCE"
            record["PERIOD_CONFIDENCE"] = "HIGH"
            diagnostics[{"FULL_TIME": "ASSIGNED_UNKNOWN_TO_FT", "1ST_HALF": "ASSIGNED_UNKNOWN_TO_P1", "2ND_HALF": "ASSIGNED_UNKNOWN_TO_P2"}[resolved]] += 1
            decision["reason_code"] = "PERIOD_EVIDENCE_UNANIMOUS"
        diagnostics["decisions"].append(decision)
    after = {period: sum(record.get("PERIOD") == period for record in canonical_records)
             for period in ("FULL_TIME", "1ST_HALF", "2ND_HALF", "UNKNOWN")}
    diagnostics.update({"AFTER_FT": after["FULL_TIME"], "AFTER_P1": after["1ST_HALF"],
                        "AFTER_P2": after["2ND_HALF"], "AFTER_UNKNOWN": after["UNKNOWN"]})
    diagnostics["decisions"].sort(key=lambda item: (tuple(item["source_raw_record_ids"]), item["reason_code"]))
    return diagnostics


def derive_market_normalization(records: list[dict[str, Any]], home_team: str, away_team: str) -> dict[str, int]:
    """Add non-semantic owner/line/handicap projections after canonical dedupe."""
    norm = lambda value: " ".join(re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", str(value or "").lower()).encode("ascii", "ignore").decode()).split())
    home, away = norm(home_team), norm(away_team)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        if record.get("FAMILY") == "HANDICAP_EUROPEAN":
            groups.setdefault((str(record.get("MARKET_INSTANCE_ID") or record.get("CONTAINER_ID") or ""), str(record.get("PERIOD") or ""), str(record.get("LINE") or "")), []).append(record)
    for record in records:
        owner = norm(record.get("OWNER"))
        market_text = norm(record.get("MARKET"))
        # Team-owned proposition titles (win-to-nil, clean sheet, exact team
        # goals, both halves, etc.) often put the team in the heading rather
        # than the selection.  Bind it only when exactly one event team is
        # present; two-team/match-level headings remain ownerless.
        mentions_home = bool(home and re.search(r"(?:^| )" + re.escape(home) + r"(?: |$)", market_text))
        mentions_away = bool(away and re.search(r"(?:^| )" + re.escape(away) + r"(?: |$)", market_text))
        column_match = re.search(r"\|column:([^|]+)", str(record.get("MARKET_INSTANCE_ID") or ""))
        column_text = norm(column_match.group(1).replace(".", " ") if column_match else record.get("COLUMN_ID"))
        record["COLUMN_ROLE"] = column_text
        if not owner:
            mentions_home = mentions_home or bool(home and re.search(r"(?:^| )" + re.escape(home) + r"(?: |$)", column_text))
            mentions_away = mentions_away or bool(away and re.search(r"(?:^| )" + re.escape(away) + r"(?: |$)", column_text))
            if "gospodarz" in column_text or "home" in column_text:
                mentions_home = True
            if "gosc" in column_text or "guest" in column_text or "away" in column_text:
                mentions_away = True
        if not owner and mentions_home != mentions_away:
            record["OWNER"] = home_team if mentions_home else away_team
            owner = home if mentions_home else away
        family, selection, line = str(record.get("FAMILY") or ""), str(record.get("SELECTION") or ""), str(record.get("LINE") or "")
        if family not in {"GOALSCORER", "PLAYER_PROP", "PLAYER_COMBINATION"}:
            record["SCORER_SCOPE"] = ""
        side = "HOME" if owner and owner == home else "AWAY" if owner and owner == away else ""
        if not side: side = "MATCH" if family in {"1X2", "DOUBLE_CHANCE", "BTTS", "GOALS_OU", "HANDICAP_EUROPEAN", "CORRECT_SCORE", "CORRECT_SCORE_GROUP", "EVENT_TOTAL", "EVENT_EXACT", "EVENT_FIRST_LAST", "EVENT_RESULT", "COMPOUND_LOGIC"} else ("OTHER" if owner else "UNKNOWN")
        sel_side = {"HOME":"HOME", "AWAY":"AWAY", "DRAW":"DRAW", "OVER":"OVER", "UNDER":"UNDER", "TAK":"YES", "NIE":"NO"}.get(selection, "OTHER" if selection else "UNKNOWN")
        line_type = "HANDICAP" if family == "HANDICAP_EUROPEAN" else ("TEAM_TOTAL" if family.startswith("TEAM_TOTALS_") else ("GOAL_TOTAL" if family == "GOALS_OU" else ("EVENT_TOTAL" if family == "EVENT_TOTAL" else "NONE")))
        kind = str(record.get("HANDICAP_KIND") or ("NONE" if line_type != "HANDICAP" else "UNKNOWN"))
        settlement = "UNKNOWN"
        if family == "DNB": settlement = "PUSH_ON_DRAW"
        elif family == "RESULT_AND_GOALS":
            # The predicate remains lossless in FAMILY/SELECTION/LINE/RAW; its
            # settlement profile is binary WIN_LOSE, including half periods.
            # This is the closed contract consumed by Context Engine V1.
            period = str(record.get("PERIOD") or "")
            valid_selection = re.fullmatch(r"(?:HOME|AWAY|DRAW)_AND_(?:OVER|UNDER)", selection)
            try:
                valid_line = bool(line) and float(line) >= 0
            except ValueError:
                valid_line = False
            settlement = "WIN_LOSE" if period in {"FULL_TIME", "1ST_HALF", "2ND_HALF"} and valid_selection and valid_line else "UNKNOWN"
        elif kind == "THREE_WAY": settlement = "WIN_DRAW_LOSE"
        elif kind == "TWO_WAY":
            try: settlement = "PUSH_POSSIBLE" if float(line).is_integer() else "NO_PUSH"
            except ValueError: settlement = "UNKNOWN"
        elif family in KNOWN_VALID_NOT_MODELED_FAMILIES:
            settlement = _known_not_modeled_settlement(family, selection)
        elif family == "CORRECT_SCORE_GROUP":
            settlement = "WIN_LOSE" if is_correct_score_group_selection(selection) else "UNKNOWN"
        elif family == "EVENT_TOTAL":
            try:
                settlement = "PUSH_POSSIBLE" if float(line).is_integer() else "NO_PUSH"
            except ValueError:
                settlement = "UNKNOWN"
        elif family in {"1X2", "DOUBLE_CHANCE", "BTTS", "GOALS_OU", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY",
                        "GOALSCORER", "PLAYER_PROP", "CORRECT_SCORE", "FIRST_GOAL_TEAM", "LAST_GOAL_TEAM",
                        "NO_GOAL", "PENALTY_GOAL", "PLAYER_COMBINATION", "EARLY_WIN_OR_TWO_GOAL_LEAD",
                        "COMPOUND_LOGIC"}:
            if family in {"GOALS_OU", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"}:
                try:
                    settlement = "PUSH_POSSIBLE" if float(line).is_integer() else "NO_PUSH"
                except ValueError:
                    settlement = "UNKNOWN"
            else:
                settlement = "WIN_LOSE"
        elif family == "HALF_FULL_RESULT":
            # The ordered half/full predicate is carried by the raw selection;
            # its resolved payout profile is binary and closed.
            settlement = "WIN_LOSE" if re.fullmatch(
                r"(?:HOME|DRAW|AWAY)_(?:HOME|DRAW|AWAY)", selection
            ) else "UNKNOWN"
        record.update({"OWNER_SIDE": side, "SELECTION_SIDE": sel_side, "LINE_TYPE": line_type,
                       "LINE_VALUE": line if line else None, "DERIVED_HANDICAP_KIND": kind,
                       "SETTLEMENT": settlement, "NORMALIZATION_STATUS": "COMPLETE" if line_type == "NONE" or line else "PARTIAL",
                       "NORMALIZATION_REASON": "DERIVED_EXPLICIT_OWNER" if side in {"HOME", "AWAY"} else "DERIVED_MATCH_LEVEL" if side == "MATCH" else "OWNER_UNKNOWN",
                       "MODELING_DISPOSITION": "KNOWN_VALID_NOT_MODELED" if family in KNOWN_VALID_NOT_MODELED_FAMILIES else "MODELED_OR_SUPPORTED"})
        if family in {"GOALSCORER", "PLAYER_PROP", "PLAYER_COMBINATION"}:
            if "pierwszy gol" in column_text or "first goal" in column_text:
                record["SCORER_SCOPE"] = "FIRST"
            elif "ostatni gol" in column_text or "last goal" in column_text:
                record["SCORER_SCOPE"] = "LAST"
            elif re.search(r"\b2\b.*\b(?:gol|goli)\b", column_text):
                record["SCORER_SCOPE"] = "TWO_OR_MORE_GOALS"
            elif re.search(r"\b3\b.*\b(?:gol|goli)\b", column_text):
                record["SCORER_SCOPE"] = "THREE_OR_MORE_GOALS"
    return {"CANONICAL_TOTAL": len(records), "OWNER_HOME": sum(r["OWNER_SIDE"] == "HOME" for r in records),
            "OWNER_AWAY": sum(r["OWNER_SIDE"] == "AWAY" for r in records), "OWNER_MATCH": sum(r["OWNER_SIDE"] == "MATCH" for r in records),
            "OWNER_UNKNOWN": sum(r["OWNER_SIDE"] == "UNKNOWN" for r in records), "LINE_PRESENT": sum(r["LINE_VALUE"] is not None for r in records),
            "LINE_MISSING": sum(r["LINE_VALUE"] is None for r in records), "HANDICAP_TWO_WAY": sum(r["DERIVED_HANDICAP_KIND"] == "TWO_WAY" for r in records),
            "HANDICAP_THREE_WAY": sum(r["DERIVED_HANDICAP_KIND"] == "THREE_WAY" for r in records)}


def _aggregate_parser_truth_status(
    tab_reports: list[dict[str, Any]],
    detected_tab_count: int = 0,
    unscanned_tabs: list[str] | None = None
) -> tuple[str, str]:
    if not tab_reports and not unscanned_tabs:
        return "FAIL", "NO"

    statuses = [t["status"] for t in tab_reports]
    unscanned_list = unscanned_tabs or []
    scanned_count = len(tab_reports)

    if unscanned_list:
        global_status = "FAIL" if ("FAIL" in statuses or any(t.get("reason") == "TAB_ACTIVATION_FAILED" for t in tab_reports)) else "PARTIAL"
    elif detected_tab_count > 0 and detected_tab_count != scanned_count:
        global_status = "FAIL" if "FAIL" in statuses else "PARTIAL"
    else:
        if "FAIL" in statuses:
            global_status = "FAIL"
        elif "PARTIAL" in statuses:
            global_status = "PARTIAL"
        else:
            global_status = "PASS"

    analysis_ready = "YES" if global_status == "PASS" else "NO"
    return global_status, analysis_ready


def _is_clean_core_unresolved(item: dict[str, Any]) -> bool:
    """Only explicit full-time canonical markets belong to the CLEAN_CORE scope."""
    market = str(item.get("MARKET") or "")
    family, _ = classify_family(market, "", "", "", "")
    period, _, _ = classify_period_detail(market, "", family=family)
    return family in CLEAN_CORE_FAMILIES and period == "FULL_TIME"


def is_player_prop_record(item: dict[str, Any]) -> bool:
    """Return true only for parser-recognised player-scoped propositions."""
    return str(item.get("FAMILY") or "") in PLAYER_PROP_FAMILIES


def _has_player_entity_scope(item: dict[str, Any]) -> bool:
    """Require a player participant for every recognised player proposition."""
    if not is_player_prop_record(item):
        return False
    participants = [str(value).strip() for value in item.get("PARTICIPANTS") or [] if str(value).strip()]
    if str(item.get("PARTICIPANT") or "").strip() or participants:
        return True
    # Goal-scorer and combination selections are the player entity when a
    # compact source omits a separate participant field.  Do not accept common
    # binary/side tokens as people.
    if str(item.get("FAMILY") or "") in {"GOALSCORER", "PLAYER_COMBINATION"}:
        selection = str(item.get("SELECTION") or "").strip()
        return selection.casefold() not in {"", "home", "away", "draw", "tak", "nie", "yes", "no", "over", "under"}
    return False


def _semantic_quarantine_scope(item: dict[str, Any]) -> str:
    """Classify a true semantic quarantine without relabelling match markets."""
    if is_player_prop_record(item):
        return "PLAYER_PROP"
    tab = unicodedata.normalize("NFKD", str(item.get("CATEGORY") or item.get("MAIN_TAB") or "")).encode("ascii", "ignore").decode().casefold()
    return "OPTIONAL_STATISTICS" if tab == "statystyki" else "MATCH_MARKET"


def _semantic_quarantine_reason(item: dict[str, Any]) -> str:
    """Fail closed when period or settlement is not proven for a retained row."""
    title = unicodedata.normalize("NFKD", str(item.get("MARKET") or "")).encode("ascii", "ignore").decode().casefold()
    tab = unicodedata.normalize("NFKD", str(item.get("CATEGORY") or item.get("MAIN_TAB") or "")).encode("ascii", "ignore").decode().casefold()
    if item.get("UNRECOGNIZED_TOP_CARD"):
        return "UNRECOGNIZED_TOP_CARD"
    if "xtra wygrana" in title:
        return "UNCONFIRMED_XTRA_PAYOUT_CONTRACT"
    if (str(item.get("FAMILY") or "") in {
            "CLEAN_SHEET", "TEAM_WIN_TO_NIL", "TEAM_SCORES_BOTH_HALVES",
            "TEAM_WINS_ONE_HALF", "TEAM_WINS_BOTH_HALVES", "TEAM_TOTALS_HOME",
            "TEAM_TOTALS_AWAY",
    } and not str(item.get("OWNER") or "").strip()):
        return "UNCONFIRMED_TEAM_OWNER"
    if is_player_prop_record(item) and not _has_player_entity_scope(item):
        return "UNCONFIRMED_PLAYER_PROP_SCOPE"
    # A Fast card settles on a selectable minute window, never the full match,
    # whichever tab displayed it.
    window_market = bool(item.get("TIME_WINDOW_MARKET")) or _declares_time_window(item)
    if item.get("PERIOD") == "UNKNOWN" or window_market:
        if is_player_prop_record(item) or "zawodnik" in title or "player" in title:
            return "UNCONFIRMED_PLAYER_PROP_PERIOD"
        if tab == "statystyki":
            return "UNSUPPORTED_OPTIONAL_STATISTICS_PERIOD"
        return "UNCONFIRMED_MARKET_PERIOD"
    if item.get("SETTLEMENT") == "UNKNOWN":
        return "UNCONFIRMED_MARKET_SETTLEMENT"
    return ""


def _declares_time_window(item: dict[str, Any]) -> bool:
    return (has_selectable_time_window(str(item.get("BOX_CONTEXT") or ""))
            or is_fast_window_tab(str(item.get("CATEGORY") or item.get("MAIN_TAB") or "")))


def mark_time_window_markets(rows: list[dict[str, Any]]) -> None:
    """Flag every copy of a minute-window card, including copies whose own tab
    text does not show the window (Top/Strzelcy copies of a Fast card share
    the Fast copy's raw source records)."""
    window_ids = {raw_id for row in rows if _declares_time_window(row)
                  for raw_id in (row.get("source_raw_record_ids") or [row.get("raw_record_id")]) if raw_id}
    for row in rows:
        ids = {raw_id for raw_id in (row.get("source_raw_record_ids") or [row.get("raw_record_id")]) if raw_id}
        if _declares_time_window(row) or ids & window_ids:
            row["TIME_WINDOW_MARKET"] = True


def is_semantically_quarantined(item: dict[str, Any]) -> bool:
    """Whether a record lacks proven period, player scope, or settlement truth."""
    return bool(_semantic_quarantine_reason(item))


def partition_semantic_records(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split records once, preserving row order and source lineage unchanged."""
    accepted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    mark_time_window_markets(rows)
    for row in rows:
        (quarantined if is_semantically_quarantined(row) else accepted).append(row)
    return accepted, quarantined


def llm_packet(match: str, competition: str, kickoff: str, accepted_odds: list[dict[str, Any]],
               readiness: dict[str, Any], empty_tabs: list[str] | None = None,
               kickoff_utc: str = "", captured_utc: str = "") -> str:
    """User/LLM odds text: every semantically accepted bet, no technical metadata."""
    complete = (readiness.get("PARSER_TRUTH_STATUS") == "PASS"
                and readiness.get("ANALYSIS_READY") == "YES")
    status = "" if complete else str(readiness.get("PARSER_TRUTH_STATUS") or "PARTIAL")
    if status and empty_tabs:
        # Tell the reader which Betclic tab delivered no offers at all.
        status += " EMPTY_TABS=" + ",".join(empty_tabs)
    return render_llm_odds({"MATCH": match, "COMPETITION": competition, "KICKOFF": kickoff,
                            "KICKOFF_UTC": kickoff_utc, "CAPTURED_UTC": captured_utc},
                           accepted_odds, status)


def attach_structural_provenance(record, source):
    """Preserve the same dedupe evidence in capture and replay; never infer it."""
    for target, key in (("PERIOD_SCOPE_ID", "period_scope_id"), ("ROW_ID", "row_id"),
                        ("COLUMN_ID", "column_id"), ("NATIVE_SELECTION_ID", "native_selection_id"),
                        ("SECTION_SOURCE", "section_source"), ("SECTION_KEY", "section_key")):
        record[target] = source.get(key) or ""


def canonical_export_boundary(parsed_records, home_team, away_team):
    """The shared production/replay canonical population, including exclusions."""
    candidates = [dict(record) for record in parsed_records]
    derive_market_normalization(candidates, home_team, away_team)
    canonical, groups, suppressed = _dedupe_canonical_export_rows(candidates)
    accepted, quarantined = partition_semantic_records(canonical)
    return canonical, accepted, quarantined, groups, suppressed


def period_accounting(export_accepted, core_quarantined, canonical_export, core_accepted=None):
    """Count UNKNOWN at named boundaries; no population silently disappears."""
    count = lambda rows: sum(row.get("PERIOD") == "UNKNOWN" for row in rows)
    return {
        "PERIOD_UNKNOWN_COUNT": count(export_accepted) + count(core_quarantined),
        "PERIOD_UNKNOWN_COUNT_SCOPE": "EMITTED_ODD_AND_CORE_SEMANTIC_QUARANTINE",
        "EXPORT_ACCEPTED_PERIOD_UNKNOWN_COUNT": count(export_accepted),
        "CORE_ACCEPTED_PERIOD_UNKNOWN_COUNT": count(export_accepted if core_accepted is None else core_accepted),
        "CORE_QUARANTINED_PERIOD_UNKNOWN_COUNT": count(core_quarantined),
        "CANONICAL_EXPORT_PERIOD_UNKNOWN_COUNT": count(canonical_export),
    }


def semantic_quarantine_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize true semantic exclusions with an explicit, disjoint scope."""
    ledger: list[dict[str, Any]] = []
    for row in rows:
        reason = _semantic_quarantine_reason(row)
        if not reason:
            continue
        ledger.append({
            "reason": reason,
            "scope": _semantic_quarantine_scope(row),
            "family": row.get("FAMILY") or "OTHER",
            "player_entity_scope": _has_player_entity_scope(row),
            "tab": row.get("CATEGORY") or row.get("MAIN_TAB") or "",
            "category": row.get("CATEGORY") or "",
            "market": row.get("MARKET") or "",
            "selection": row.get("SELECTION") or "",
            "owner": row.get("OWNER") or "",
            "participant": row.get("PARTICIPANT") or "",
            "participants": list(row.get("PARTICIPANTS") or []),
            "odds": row.get("ODDS") or "",
            "raw_original": row.get("RAW_ORIGINAL") or row.get("RAW") or "",
            "period": row.get("PERIOD") or "UNKNOWN",
            "settlement": row.get("SETTLEMENT") or "UNKNOWN",
            "declared_winning_event": row.get("DECLARED_WINNING_EVENT") or "",
            "winning_event_source": row.get("WINNING_EVENT_SOURCE") or "",
            "payout_contract": row.get("PAYOUT_CONTRACT") or "",
            "contract_missing": row.get("CONTRACT_MISSING") or "",
            "period_source": row.get("PERIOD_SOURCE") or "",
            "period_confidence": row.get("PERIOD_CONFIDENCE") or "",
            "raw_record_id": row.get("raw_record_id") or "",
            "source_raw_record_ids": list(row.get("source_raw_record_ids") or []),
            "market_instance_id": row.get("MARKET_INSTANCE_ID") or "",
            "dom_path": row.get("DOM_PATH") or "",
            "section_path": row.get("SECTION_PATH") or "",
            "section_source": row.get("SECTION_SOURCE") or "",
            "box_context": row.get("BOX_CONTEXT") or "",
        })
    return ledger


def semantic_quarantine_scope_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Return a fixed, mutually exclusive accounting view for quarantined rows."""
    counts = {"PLAYER_PROP": 0, "MATCH_MARKET": 0, "OPTIONAL_STATISTICS": 0}
    for item in semantic_quarantine_ledger(rows):
        counts[item["scope"]] += 1
    return counts


def build_accounting_layers(*, source_raw_records: int, source_identity_representatives: int,
                            upstream_player_prop_excluded: int, upstream_other_excluded: int,
                            canonical_export_representatives: int, semantic_accepted: int,
                            semantic_quarantined: int, core_usable: int | None,
                            core_semantic_quarantined: int | None,
                            core_postprocessing_excluded: int, unresolved: int) -> dict[str, Any]:
    """Build the single, layer-labelled accounting contract used by runtime and replay."""
    return {
        "ACCOUNTING_SCHEMA_VERSION": ACCOUNTING_SCHEMA_VERSION,
        "SEMANTIC_QUARANTINE_SCHEMA_VERSION": SEMANTIC_QUARANTINE_SCHEMA_VERSION,
        "ACCOUNTING_DEFINITIONS": {
            "SOURCE_RAW_RECORDS": "priced capture rows supplied to parsing",
            "SOURCE_IDENTITY_REPRESENTATIVES": "rows after identity dedupe; duplicate source IDs remain in lineage",
            "UPSTREAM_EXCLUDED": "rows intentionally excluded before canonical semantic classification",
            "CANONICAL_EXPORT_REPRESENTATIVES": "rows after canonical export dedupe before semantic acceptance",
            "SEMANTIC_ACCEPTED": "canonical export rows with proven scope, period, and settlement",
            "SEMANTIC_QUARANTINED": "canonical export rows fail-closed for unproven scope, period, or settlement",
            "CORE_USABLE": "source-identity representatives retained for the context core after post-processing",
            "CORE_POSTPROCESSING_EXCLUDED": "source-identity representatives excluded from the core for an audited non-semantic reason",
            "UNRESOLVED": "parser or capture issues retained outside semantic acceptance",
        },
        "SOURCE_RAW_RECORDS": source_raw_records,
        "SOURCE_IDENTITY_REPRESENTATIVE_COUNT": source_identity_representatives,
        "SOURCE_DUPLICATE_ROWS_SUPPRESSED": max(0, source_raw_records - source_identity_representatives),
        "UPSTREAM_PLAYER_PROP_EXCLUDED_COUNT": upstream_player_prop_excluded,
        "UPSTREAM_OTHER_EXCLUDED_COUNT": upstream_other_excluded,
        "CANONICAL_EXPORT_REPRESENTATIVE_COUNT": canonical_export_representatives,
        "SEMANTIC_REPRESENTATIVE_COUNT": canonical_export_representatives,
        "SEMANTIC_ACCEPTED_COUNT": semantic_accepted,
        "SEMANTIC_QUARANTINED_COUNT": semantic_quarantined,
        "CORE_USABLE_REPRESENTATIVE_COUNT": core_usable,
        "CORE_REPRESENTATIVE_SEMANTIC_QUARANTINED_COUNT": core_semantic_quarantined,
        "CORE_POSTPROCESSING_EXCLUDED_REPRESENTATIVE_COUNT": core_postprocessing_excluded,
        "UNRESOLVED_COUNT": unresolved,
        "CANONICAL_SEMANTIC_ACCOUNTING_CONSISTENT": canonical_export_representatives == semantic_accepted + semantic_quarantined,
    }


def _is_optional_statistics_exclusion(tab_name: str, priced: int, dom_items: list[dict[str, Any]],
                                      unaccounted: int) -> bool:
    """Fail closed: Statistics is optional only when it produced no usable row."""
    normalized = unicodedata.normalize("NFKD", str(tab_name or "")).encode("ascii", "ignore").decode().casefold()
    return normalized == "statystyki" and priced > 0 and not dom_items and unaccounted == 0


def _evaluate_clean_core_gate(
    odds: list[dict[str, Any]], unresolved: list[dict[str, Any]], structural_reasons: list[str]
) -> dict[str, Any]:
    """Report a separately scoped readiness signal without relaxing exhaustive readiness."""
    core_unknown = sum(
        item.get("FAMILY") in CLEAN_CORE_FAMILIES and item.get("PERIOD") == "UNKNOWN"
        for item in odds
    )
    core_unresolved = sum(_is_clean_core_unresolved(item) for item in unresolved)
    excluded_unknown = sum(item.get("PERIOD") == "UNKNOWN" for item in odds) - core_unknown
    excluded_unresolved = len(unresolved) - core_unresolved
    ready = "YES" if not structural_reasons and not core_unknown and not core_unresolved else "NO"
    return {
        "clean_core_ready": ready,
        "analysis_scope": "CLEAN_CORE_ONLY" if ready == "YES" else "CLEAN_CORE_BLOCKED",
        "core_unknown_count": core_unknown,
        "core_unresolved_count": core_unresolved,
        "excluded_unknown_count": excluded_unknown,
        "excluded_unresolved_count": excluded_unresolved,
    }


def _readiness_snapshot(analysis_ready: str, full_usable_ready: str, exhaustive_ready: str,
                        analysis_scope: str, parser_truth_status: str) -> dict[str, str]:
    """Immutable final readiness truth shared by every output channel."""
    return {
        "ANALYSIS_READY": analysis_ready,
        "FULL_USABLE_READY": full_usable_ready,
        "EXHAUSTIVE_READY": exhaustive_ready,
        "ANALYSIS_SCOPE": analysis_scope,
        "PARSER_TRUTH_STATUS": parser_truth_status,
    }


def _dedupe_records_preserving_order(
    extracted_odds: list[dict[str, str]],
    unresolved_items: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    unique_odds: list[dict[str, str]] = []
    seen_collision_records: dict[tuple, dict[str, Any]] = {}

    def merge_lineage(survivor: dict[str, Any], incoming: dict[str, Any]) -> None:
        for field in ("run_id", "event_id", "source_hash"):
            if survivor.get(field) and incoming.get(field) and survivor[field] != incoming[field]:
                raise ValueError(f"LINEAGE_CONTEXT_MISMATCH:{field}")
        ids = list(survivor.get("source_raw_record_ids") or ([] if not survivor.get("raw_record_id") else [survivor["raw_record_id"]]))
        ids += list(incoming.get("source_raw_record_ids") or ([] if not incoming.get("raw_record_id") else [incoming["raw_record_id"]]))
        survivor["source_raw_record_ids"] = list(dict.fromkeys(ids))
        if incoming.get("TIME_WINDOW_MARKET") or _declares_time_window(incoming):
            survivor["TIME_WINDOW_MARKET"] = True

    def process_item(item: dict[str, str]) -> bool:
        # Physical capture provenance is deliberately *not* semantic identity.
        # The same offer is commonly exposed in Top, Wynik and a specialised
        # tab; those views must collapse while retaining every source row.
        # Keep every field that can alter settlement, period, player subtype
        # or market side so that visually similar but different offers remain
        # distinct.
        raw_label = re.sub(r"\s+[1-9]\d{0,2}(?:[.,]\d{1,2})?\s*$", "", str(item.get("RAW") or "")).strip().casefold()
        instance_id = str(item.get("MARKET_INSTANCE_ID") or "")
        column_match = re.search(r"\|column:([^|]+)", instance_id)
        column_role = str(item.get("COLUMN_ID") or (column_match.group(1) if column_match else ""))
        col_key = (
            item.get("FAMILY", ""),
            item.get("PERIOD", ""),
            item.get("SETTLEMENT_SCOPE", ""),
            item.get("MARKET_SCOPE", ""),
            item.get("MARKET", "").strip().lower(),
            item.get("OWNER", ""),
            item.get("SELECTION", ""),
            item.get("LINE", ""),
            item.get("SCORER_SCOPE") or "",
            item.get("HANDICAP_KIND", ""),
            item.get("SETTLEMENT", ""),
            column_role,
            raw_label,
        )
        # Older captures did not preserve the scope/column evidence needed to
        # distinguish responsive representations safely.  Preserve their
        # historical replay contract rather than applying the modern union
        # collapse on incomplete provenance.
        if item.get("_legacy_capture_schema") or not (item.get("PERIOD_SCOPE_ID") or item.get("period_scope_id")):
            col_key += (instance_id, str(item.get("DOM_PATH") or ""), str(item.get("ACTIVE_TAB") or ""))
        curr_odds = item.get("ODDS", "")
        curr_tab = item.get("CATEGORY") or item.get("tab_name") or ""
        curr_cap = item.get("capture_id") or ""
        curr_src = item.get("source_index", 0)

        if col_key in seen_collision_records:
            prev_info = seen_collision_records[col_key]
            prev_item = prev_info["record"]
            prev_odds = prev_item.get("ODDS", "")
            prev_tab = prev_item.get("CATEGORY") or prev_item.get("tab_name") or ""
            prev_cap = prev_item.get("capture_id") or ""
            prev_src = prev_item.get("source_index", 0)

            if prev_odds == curr_odds:
                merge_lineage(prev_item, item)
                prev_item["representation_count"] = int(prev_item.get("representation_count") or 1) + int(item.get("representation_count") or 1)
                # Same odds duplicate -> merge, keeping latest source_index
                if curr_src > prev_src:
                    item["source_raw_record_ids"] = list(prev_item.get("source_raw_record_ids") or [])
                    item["representation_count"] = prev_item["representation_count"]
                    idx = prev_info["index_in_unique"]
                    unique_odds[idx] = item
                    seen_collision_records[col_key] = {"record": item, "index_in_unique": idx}
                return False
            else:
                # Different odds!
                same_instance = bool(item.get("MARKET_INSTANCE_ID")) and item.get("MARKET_INSTANCE_ID") == prev_item.get("MARKET_INSTANCE_ID")
                current_hidden = item.get("SOURCE_VISIBILITY") == "HIDDEN"
                previous_hidden = prev_item.get("SOURCE_VISIBILITY") == "HIDDEN"
                if same_instance and current_hidden != previous_hidden:
                    # Explicit responsive-state evidence: keep the visible row.
                    if previous_hidden:
                        idx = prev_info["index_in_unique"]
                        unique_odds[idx] = item
                        seen_collision_records[col_key] = {"record": item, "index_in_unique": idx}
                    return False
                is_different_snapshot = (prev_cap and curr_cap and prev_cap != curr_cap) or (not prev_cap and not curr_cap and prev_tab != curr_tab)
                if is_different_snapshot:
                    # TICK_MOVE across different evaluation snapshots -> keep record with highest source_index
                    if curr_src > prev_src:
                        idx = prev_info["index_in_unique"]
                        unique_odds[idx] = item
                        seen_collision_records[col_key] = {"record": item, "index_in_unique": idx}
                    return False
                else:
                    # Conflicting odds within the SAME evaluation snapshot -> TRUE_CONFLICT!
                    unresolved_items.append({
                        "MARKET": item.get("MARKET", ""),
                        "RAW": item.get("RAW", ""),
                        "REASON": "CONFLICTING_ODDS_FOR_SAME_SELECTION",
                        "CONTAINER_ID": item.get("CONTAINER_ID", "")
                    })
                    return False

        # First time seeing this collision key
        seen_collision_records[col_key] = {"record": item, "index_in_unique": len(unique_odds)}
        return True

    for item in extracted_odds:
        if process_item(item):
            unique_odds.append(item)

    return unique_odds, unresolved_items


def _dedupe_canonical_export_rows(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """Collapse only identical displayed propositions at the packet boundary."""
    fields = ("CATEGORY", "FAMILY", "MARKET", "PERIOD", "OWNER", "PARTICIPANT", "PARTICIPANTS", "SELECTION", "LINE",
              "HANDICAP_KIND", "HANDICAP_TAXONOMY", "SETTLEMENT", "ODDS", "SCORER_SCOPE", "COLUMN_ROLE")
    unique: list[dict[str, Any]] = []
    seen: dict[tuple[str, ...], int] = {}
    groups: set[tuple[str, ...]] = set()
    for original in sorted(records, key=lambda row: (
            str(row.get("raw_record_id") or ""), str(row.get("MARKET_INSTANCE_ID") or ""),
            json.dumps(row, ensure_ascii=False, sort_keys=True))):
        record = dict(original)
        record["source_raw_record_ids"] = sorted(set(original.get("source_raw_record_ids") or []))
        raw_label = re.sub(r"\s+[1-9]\d{0,2}(?:[.,]\d{1,2})?\s*$", "", str(record.get("RAW_ORIGINAL") or record.get("RAW") or "")).strip()
        key = (*(str(record.get(field) or "").strip() for field in fields), raw_label)
        if key not in seen:
            seen[key] = len(unique)
            unique.append(record)
            continue
        groups.add(key)
        survivor = unique[seen[key]]
        ids = list(survivor.get("source_raw_record_ids") or []) + list(record.get("source_raw_record_ids") or [])
        survivor["source_raw_record_ids"] = sorted(set(ids))
        if record.get("TIME_WINDOW_MARKET") or _declares_time_window(record):
            survivor["TIME_WINDOW_MARKET"] = True
        survivor["representation_count"] = int(survivor.get("representation_count") or 1) + int(record.get("representation_count") or 1)
    return unique, len(groups), len(records) - len(unique)


def _semantic_text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore").decode().casefold().split())


def _settlement_signature(record: dict[str, Any]) -> str:
    """A deliberately conservative signature of mathematically identical bets.

    Empty means that the parser has no proof of equivalence.  Similar markets are
    therefore never grouped merely because their names or odds look alike.
    """
    event = str(record.get("event_id") or "")
    period = str(record.get("PERIOD") or "")
    family = str(record.get("FAMILY") or "")
    selection = str(record.get("SELECTION") or "")
    line = str(record.get("LINE") or "")
    category = _semantic_text(record.get("CATEGORY") or record.get("MAIN_TAB") or "")
    metric = _semantic_text(f"{record.get('MARKET')} {record.get('RAW')}".replace("ł", "l").replace("Ł", "L"))
    if any(token in metric for token in ("kartk", "rzuty rozne", "strzal", "faule", "spalon", "odbiory", "podan")):
        return ""
    base = f"{event}|{period}|"
    if family == "1X2" and selection in {"HOME", "AWAY", "DRAW"} and category != "statystyki":
        return base + "FOOTBALL_RESULT|RESULT:" + selection
    if family == "HANDICAP_EUROPEAN" and category != "statystyki" and record.get("HANDICAP_KIND") == "TWO_WAY" and line == "-0.5" and selection in {"HOME", "AWAY"}:
        return base + "FOOTBALL_RESULT|RESULT:" + selection
    if (family == "COMPOUND_LOGIC" and record.get("SETTLEMENT") == "WIN_LOSE"
            and line == "2.5" and not record.get("OWNER")
            and selection in {"BTTS_OR_OVER_NO", "BTTS_NO_AND_UNDER"}):
        return base + "FOOTBALL_GOALS|NOT_BTTS_AND_UNDER:2.5"
    return ""


def build_equivalence_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only proven multi-representation settlement equivalences."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        signature = _settlement_signature(record)
        if signature:
            groups.setdefault(signature, []).append(record)
    result: list[dict[str, Any]] = []
    for signature, copies in sorted(groups.items()):
        if len(copies) < 2:
            continue
        def odds_value(item: dict[str, Any]) -> float:
            try:
                return float(str(item.get("ODDS") or "").replace(",", "."))
            except ValueError:
                return 0.0
        ordered = sorted(copies, key=lambda item: (-odds_value(item), str(item.get("MARKET") or ""), str(item.get("raw_record_id") or "")))
        best = ordered[0]
        best_odds = odds_value(best)
        result.append({
            "signature": signature,
            "best_odds": str(best.get("ODDS") or ""),
            "best_market": str(best.get("MARKET") or ""),
            "best_category": str(best.get("CATEGORY") or ""),
            "copies": [{"market": str(item.get("MARKET") or ""), "category": str(item.get("CATEGORY") or ""),
                        "odds": str(item.get("ODDS") or ""),
                        "delta_percent": round(((best_odds / odds_value(item)) - 1) * 100, 2) if odds_value(item) else None,
                        "source_raw_record_ids": list(item.get("source_raw_record_ids") or [])}
                       for item in ordered],
        })
    return result


def analyze_handicap_completeness(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify handicap instances from row-local lines without changing semantics.

    `MARKET_INSTANCE_ID` is cell-level in current captures, so the stable container
    prefix is used for pairing; the diagnostic identity additionally includes the
    logical market/period/absolute line to suppress Top/Wynik representations.
    """
    groups: dict[tuple[str, str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        if record.get("FAMILY") != "HANDICAP_EUROPEAN" or not record.get("LINE"):
            continue
        try:
            absolute = f"{abs(float(str(record['LINE']).replace(',', '.'))):g}"
        except ValueError:
            continue
        instance = str(record.get("CONTAINER_ID") or record.get("MARKET_INSTANCE_ID") or "")
        instance = instance.split("|row#", 1)[0].split("|cell:", 1)[0]
        key = (str(record.get("run_id") or ""), str(record.get("event_id") or ""),
               str(record.get("source_hash") or ""), str(record.get("PERIOD") or ""),
               str(record.get("HANDICAP_KIND") or "THREE_WAY"), str(record.get("MARKET") or ""),
               instance + "|" + absolute)
        groups.setdefault(key, []).append(record)
    incomplete: list[dict[str, Any]] = []
    excluded_ids: set[int] = set()
    for key, rows in groups.items():
        kind = key[4]
        expected = {"HOME", "AWAY"} if kind == "TWO_WAY" else {"HOME", "DRAW", "AWAY"}
        actual = {str(row.get("SELECTION") or "") for row in rows}
        if expected <= actual:
            continue
        for row in rows:
            excluded_ids.add(id(row))
        logical = "|".join((key[0], key[1], key[2], key[3], key[4], key[5], key[6].rsplit("|", 1)[-1]))
        incomplete.append({
            "incomplete_instance_id": "inc_" + hashlib.sha256(logical.encode("utf-8")).hexdigest()[:20],
            "run_id": key[0], "event_id": key[1], "source_hash": key[2], "period": key[3],
            "handicap_kind": kind, "market": key[5], "logical_line": key[6].rsplit("|", 1)[-1],
            "expected": sorted(expected), "actual": sorted(actual), "records": rows,
        })
    # Multiple tabs may expose the same deficient logical instance.  Preserve all
    # lineage but produce one packet diagnostic with a representation count.
    deduped: dict[tuple[str, str, str, str, str, str, str], dict[str, Any]] = {}
    for entry in incomplete:
        logical_key = tuple(entry[field] for field in ("run_id", "event_id", "source_hash", "period", "handicap_kind", "market", "logical_line"))
        target = deduped.setdefault(logical_key, {**entry, "records": []})
        target["records"].extend(entry["records"])
    for entry in deduped.values():
        entry["representation_count"] = len(entry["records"])
        entry["source_raw_record_ids"] = list(dict.fromkeys(
            source_id for row in entry["records"]
            for source_id in (row.get("source_raw_record_ids") or ([row["raw_record_id"]] if row.get("raw_record_id") else []))))
        entry["source_tabs"] = sorted({str(row.get("MAIN_TAB") or row.get("CATEGORY") or "") for row in entry["records"]})
    return {"excluded_record_ids": excluded_ids, "incomplete_instances": list(deduped.values()),
            "duplicate_rows_suppressed": max(0, len(incomplete) - len(deduped))}


def completeness_breakdown(*, detected_tabs: int, scanned_tabs: int, raw_records: int,
                           parsed_records: int, unknown_periods: int,
                           incomplete_instances: int, excluded_rows: int,
                           unaccounted_priced: int = 0) -> dict[str, Any]:
    """Deterministic 0-100 mean of coverage, parse, period, instances, exclusion.

    Every denominator is current-run evidence.  Unique incomplete instances, rather
    than duplicate rows from Top/Wynik, drive the instance penalty; adding an
    incomplete instance can never increase the resulting score.
    """
    ratio = lambda good, total: 100.0 if total <= 0 else round(100.0 * max(0, min(good, total)) / total, 1)
    tab = ratio(scanned_tabs, detected_tabs) if not unaccounted_priced else 0.0
    parse = ratio(parsed_records, raw_records)
    period = ratio(max(0, parsed_records - unknown_periods), parsed_records)
    instances = ratio(max(0, parsed_records - incomplete_instances), parsed_records)
    exclusion = ratio(max(0, raw_records - excluded_rows), raw_records)
    score = round((tab + parse + period + instances + exclusion) / 5, 1)
    return {"COMPLETENESS_SCORE": score, "COMPLETENESS_TAB_COVERAGE": tab,
            "COMPLETENESS_PARSE": parse, "COMPLETENESS_PERIOD": period,
            "COMPLETENESS_MARKET_INSTANCES": instances, "COMPLETENESS_EXCLUSION": exclusion,
            "UNIQUE_INCOMPLETE_INSTANCE_COUNT": incomplete_instances,
            "DUPLICATE_INCOMPLETE_ROWS_SUPPRESSED": max(0, excluded_rows - incomplete_instances),
            "UNACCOUNTED_PRICED_COUNT": unaccounted_priced}


def find_chrome_exe() -> str | None:
    candidates: list[str] = []
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        candidates.extend(str(path) for path in (
            bundle_root / "browser" / "chrome-win" / "chrome.exe",
            bundle_root / "browser" / "chrome-win64" / "chrome.exe",
        ))
    candidates.extend([
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), r"Google\Chrome\Application\chrome.exe"),
    ])
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _expand_all_on_page(page: Any, diag: DiagnosticsManager, max_deadline: float) -> int:
    total_clicked = 0
    stable_passes = 0
    prev_state: tuple[int, int, int, int] | None = None
    reached_deadline = False

    selector_query = (
        "button[aria-expanded='false'], "
        ".marketBox_header.is-closed, "
        "button:has-text('Pokaż więcej'), "
        "span:has-text('Pokaż więcej'), "
        "button:has-text('Więcej'), "
        "span:has-text('Więcej')"
    )

    pass_count = 0
    for pass_idx in range(1, 9):
        if time.time() > max_deadline:
            reached_deadline = True
            break
        pass_count = pass_idx
        clicked_in_pass = 0

        # Start each pass from top of document
        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        time.sleep(0.04)

        try:
            viewport_h = page.evaluate("window.innerHeight || 800")
            step = max(500, int(viewport_h * 0.8))
        except Exception:
            viewport_h = 800
            step = 600

        current_y = 0
        while True:
            if time.time() > max_deadline:
                reached_deadline = True
                break

            try:
                buttons = page.query_selector_all(selector_query)
            except Exception:
                buttons = []

            clicked_handles: set[str] = set()
            for btn in buttons:
                if time.time() > max_deadline:
                    reached_deadline = True
                    break
                try:
                    if not btn.is_visible():
                        continue

                    # Avoid clicking child span and parent button twice in same pass
                    elem_key = btn.evaluate("el => el.getAttribute('id') || (el.innerText || '').slice(0, 40)")
                    if elem_key in clicked_handles:
                        continue

                    cls = (btn.get_attribute("class") or "").lower()
                    txt = btn.inner_text().strip()

                    if "is-odd" in cls or "odd" in cls or btn.is_disabled():
                        continue
                    if re.match(r"^\d+[\.,]\d{2}$", txt):
                        continue

                    btn.click()
                    clicked_handles.add(elem_key)
                    clicked_in_pass += 1
                    total_clicked += 1
                    time.sleep(0.04)
                except Exception:
                    pass

            try:
                scroll_h = page.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)")
            except Exception:
                scroll_h = current_y + viewport_h

            if current_y + viewport_h >= scroll_h:
                break

            current_y += step
            try:
                page.evaluate(f"window.scrollTo(0, {current_y})")
            except Exception:
                pass
            time.sleep(0.04)

        try:
            scroll_h = page.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)")
            selectable = page.evaluate("document.querySelectorAll('button.is-odd, button[class*=\"odd\"], [class*=\"oddValue\"]').length")
            rem_closed = page.evaluate("document.querySelectorAll('button[aria-expanded=\"false\"], .marketBox_header.is-closed').length")
            rem_more = page.evaluate("Array.from(document.querySelectorAll('button, span')).filter(el => { const t = el.innerText ? el.innerText.trim() : ''; return t === 'Pokaż więcej' || t === 'Więcej'; }).length")
        except Exception:
            scroll_h, selectable, rem_closed, rem_more = 0, 0, 0, 0

        curr_state = (scroll_h, selectable, rem_closed, rem_more)

        if clicked_in_pass == 0 and curr_state == prev_state:
            stable_passes += 1
            if stable_passes >= 2:
                break
        else:
            stable_passes = 0

        prev_state = curr_state

    try:
        selectable = page.evaluate("document.querySelectorAll('button.is-odd, button[class*=\"odd\"], [class*=\"oddValue\"]').length")
        rem_closed = page.evaluate("document.querySelectorAll('button[aria-expanded=\"false\"], .marketBox_header.is-closed').length")
        rem_more = page.evaluate("Array.from(document.querySelectorAll('button, span')).filter(el => { const t = el.innerText ? el.innerText.trim() : ''; return t === 'Pokaż więcej' || t === 'Więcej'; }).length")
    except Exception:
        selectable, rem_closed, rem_more = 0, 0, 0

    deadline_str = "YES" if reached_deadline else "NO"
    if diag:
        diag.log(f"EXPANSION_RESULT passes={pass_count} clicked={total_clicked} remaining_closed={rem_closed} remaining_more={rem_more} selectable={selectable} deadline={deadline_str}")

    return total_clicked


def _make_dom_script() -> str:
    NL = "\n"
    RE_NL  = "/\\n+/g"
    RE_SP  = "/\\s+/g"
    RE_WS  = "/\\s{2,}/g"
    CLEAN_FN = "  function cleanText(s) { if (!s) return ''; return s.replace(" + RE_NL + ", ' ').replace(" + RE_WS + ", ' ').trim(); }" + NL

    script = (
        "(currentTabName) => {" + NL
        + CLEAN_FN
        + "  const results = [];" + NL
        + "  const siblingIndex = e => { if(!e||!e.parentElement)return 0; return Array.prototype.indexOf.call(e.parentElement.children,e); };" + NL
        + "  const nodePath = e => { const out=[]; for(let n=e;n&&n!==document.body;n=n.parentElement){ const tag=n.tagName?n.tagName.toLowerCase():''; const key=n.getAttribute('data-qa')||n.getAttribute('data-testid')||n.id||n.className||''; out.push(tag+'['+String(key).replace(/\\s+/g,'.').slice(0,60)+'#'+siblingIndex(n)+']'); } return out.reverse().join('>'); };" + NL
        + "  const isMyCombi = (currentTabName || '').trim().toLowerCase().includes('mycombi');" + NL
        # Section (category) context is bound structurally, never by the first
        # header found anywhere below a shared ancestor.  Betclic renders
        # marketBox_categoryTitle headings as flat siblings of the markets in
        # one scroller list and links them by data-section; the old
        # ancestor.querySelector walk returned the list's first heading for
        # every market in the tab.  Resolution stops at the innermost scope
        # that owns headings and never climbs above the market list root, so
        # page chrome and statistics widgets cannot become market context.
        + "  const SECTION_HEADER_SEL = '.marketBox_categoryTitle, .accordion_header, .sectionHeader, .marketBox_groupTitle, [class*=\"accordionTitle\"], [class*=\"groupTitle\"], [class*=\"accordion_head\"], [class*=\"categoryTitle\"]';" + NL
        + "  const MARKET_BOUNDARY_SEL = 'div.marketBox, sports-market';" + NL
        + "  const MARKET_LIST_ROOT_SEL = '.verticalScroller_list, sports-match-markets, [role=\"tabpanel\"]';" + NL
        + "  const sectionKeyOf = e => { const s = e && e.closest ? e.closest('[data-section]') : null; return s ? String(s.getAttribute('data-section') || '') : ''; };" + NL
        + "  const sectionCache = new Map();" + NL
        + "  const resolveSection = (anchor, marketTitle) => {" + NL
        + "    const cacheKey = marketTitle;" + NL
        + "    let perAnchor = sectionCache.get(anchor);" + NL
        + "    if (perAnchor && perAnchor.has(cacheKey)) return perAnchor.get(cacheKey);" + NL
        + "    const ownKey = sectionKeyOf(anchor);" + NL
        + "    let result = { title: '', source: 'NONE', key: ownKey };" + NL
        + "    let branch = anchor;" + NL
        + "    for (let scope = anchor.parentElement; scope && scope !== document.body; branch = scope, scope = scope.parentElement) {" + NL
        + "      const headers = Array.from(scope.querySelectorAll(SECTION_HEADER_SEL)).filter(h => {" + NL
        + "        if (branch.contains(h) || h.contains(anchor)) return false;" + NL
        + "        const hostMarket = h.closest(MARKET_BOUNDARY_SEL);" + NL
        + "        if (hostMarket && !hostMarket.contains(anchor)) return false;" + NL
        + "        const t = cleanText(h.innerText || h.textContent);" + NL
        + "        return Boolean(t) && t.length < 80;" + NL
        + "      });" + NL
        + "      if (headers.length) {" + NL
        + "        const preceding = headers.filter(h => h.compareDocumentPosition(branch) & Node.DOCUMENT_POSITION_FOLLOWING);" + NL
        + "        let chosen = null; let source = '';" + NL
        + "        if (ownKey) {" + NL
        + "          chosen = preceding.filter(h => sectionKeyOf(h) === ownKey).pop() || headers.find(h => sectionKeyOf(h) === ownKey) || null;" + NL
        + "          source = 'DATA_SECTION_HEADER';" + NL
        + "          if (!chosen) { const near = preceding[preceding.length - 1]; if (near && !sectionKeyOf(near)) { chosen = near; source = 'PRECEDING_SECTION_HEADER'; } }" + NL
        + "        } else {" + NL
        + "          chosen = preceding[preceding.length - 1] || null;" + NL
        + "          source = 'PRECEDING_SECTION_HEADER';" + NL
        + "        }" + NL
        + "        const chosenTitle = chosen ? cleanText(chosen.innerText || chosen.textContent) : '';" + NL
        + "        if (!chosen) result = { title: '', source: 'NONE_UNBOUND_SECTION_HEADERS', key: ownKey };" + NL
        + "        else if (chosenTitle === marketTitle) result = { title: '', source: 'SECTION_HEADER_EQUALS_MARKET_TITLE', key: ownKey };" + NL
        + "        else result = { title: chosenTitle, source: source, key: ownKey };" + NL
        + "        break;" + NL
        + "      }" + NL
        + "      if (scope.matches(MARKET_LIST_ROOT_SEL)) break;" + NL
        + "    }" + NL
        + "    if (!perAnchor) { perAnchor = new Map(); sectionCache.set(anchor, perAnchor); }" + NL
        + "    perAnchor.set(cacheKey, result);" + NL
        + "    return result;" + NL
        + "  };" + NL
        + "  const rawElements = Array.from(document.querySelectorAll('button.is-odd, button[class*=\"odd\"], [class*=\"oddValue\"]'));" + NL
        + "  const seenButtons = new Set();" + NL
        + "  let sourceIndex = 0;" + NL
        + "  for (const rawEl of rawElements) {" + NL
        + "    const btn = rawEl.closest('button') || rawEl;" + NL
        + "    if (seenButtons.has(btn)) continue;" + NL
        + "    seenButtons.add(btn);" + NL
        + "    if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') continue;" + NL
        # The persistent bet slip is application state rendered beside every
        # tab (its MyCombi state has a dedicated extractor).  Its readonly
        # price copies are never market rows; excluding them here covers the
        # crawler, the Strzelcy retry and the zero-raw active-panel fallback.
        + "    if (btn.closest('sports-betting-slip')) continue;" + NL
        + "    const oddsEl = btn.querySelector('.oddValue, [class*=\"oddValue\"], .is-oddValue') || btn;" + NL
        + "    let oddsText = cleanText(oddsEl.innerText || oddsEl.textContent);" + NL
        + "    const m = Array.from(oddsText.matchAll(/([1-9]\\d{0,2}(?:[.,]\\d{1,2})?)/g)).pop();" + NL
        + "    let oddsVal = null;" + NL
        + "    if (m) {" + NL
        + "      const val = parseFloat(m[1].replace(',', '.'));" + NL
        + "      if (val > 1.00) {" + NL
        + "        oddsVal = m[1].replace(',', '.');" + NL
        + "      }" + NL
        + "    }" + NL
        + "    if (!oddsVal) continue;" + NL
        + "    sourceIndex++;" + NL
        + "    const lineEl = btn.closest('.marketBox_lineSelection, .market_line, .marketBox_line, [class*=\"lineSelection\"]');" + NL
        + "    let marketBox = btn.closest('div.marketBox, sports-market');" + NL
        + "    let marketTitle = '';" + NL
        + "    let isMissingHeader = false;" + NL
        + "    const isTopMyCombiCard = !!btn.closest('sports-top-my-combi');" + NL
        + "    let containerId = 'box_single_' + currentTabName.replace(" + RE_SP + ", '_');" + NL
        + "    if (marketBox) {" + NL
        + "      const headerEl = marketBox.querySelector('.marketBox_headTitle, .marketBox_head, .market_header, h2, h3, h4');" + NL
        + "      if (headerEl) {" + NL
        + "        const rawHeader = cleanText(headerEl.innerText || headerEl.textContent);" + NL
        + "        if (rawHeader && rawHeader.length < 80) {" + NL
        + "          marketTitle = rawHeader;" + NL
        + "        }" + NL
        + "      }" + NL
        + "      const allBoxes = Array.from(document.querySelectorAll('div.marketBox, sports-market'));" + NL
        + "      const boxIdx = allBoxes.indexOf(marketBox);" + NL
        + "      if (boxIdx >= 0) {" + NL
        + "        containerId = 'box_' + boxIdx + '_' + currentTabName.replace(" + RE_SP + ", '_');" + NL
        + "      }" + NL
        + "    }" + NL
        + "    const hadMarketHeader = Boolean(marketTitle);" + NL
        + "    if (!marketTitle) {" + NL
        + "      if (isMyCombi) {" + NL
        + "        marketTitle = 'MyCombi';" + NL
        + "      } else {" + NL
        + "        isMissingHeader = true;" + NL
        + "      }" + NL
        + "    }" + NL
        + "    let selectionLabel = '';" + NL
        + "    let sectionTitle = '';" + NL
        + "    let ancestorTitle = '';" + NL
        + "    if (lineEl) {" + NL
        + "      const labelEl = lineEl.querySelector('.marketBox_label, .market_label, [class*=\"label\"]');" + NL
        + "      if (labelEl) {" + NL
        + "        selectionLabel = cleanText(labelEl.innerText || labelEl.textContent);" + NL
        + "      }" + NL
        + "      const splitBody = lineEl.closest('.marketBox_body');" + NL
        + "      if (splitBody) {" + NL
        + "        const titleEl = splitBody.querySelector('.marketBox_bodyTitle, [class*=\"bodyTitle\"]');" + NL
        + "        if (titleEl) sectionTitle = cleanText(titleEl.innerText || titleEl.textContent);" + NL
        + "      }" + NL
        + "    }" + NL
        + "    const sliderEl = lineEl ? lineEl.querySelector('.forms_slider') : null;" + NL
        + "    const participantHint = sliderEl ? selectionLabel : null;" + NL
        + "    const sliderSelectionEl = sliderEl ? btn.querySelector('bcdk-bet-button-label, .btn_label.is-top') : null;" + NL
        + "    const sliderSelectionLabel = sliderSelectionEl ? cleanText(sliderSelectionEl.innerText || sliderSelectionEl.textContent) : '';" + NL
        + "    const sectionContext = resolveSection(marketBox || btn, marketTitle);" + NL
        + "    ancestorTitle = sectionContext.title;" + NL
        + "    if (!sectionTitle && ancestorTitle) sectionTitle = ancestorTitle;" + NL
        + "    if (isTopMyCombiCard && !hadMarketHeader && !sectionTitle && !ancestorTitle) continue;" + NL
        + "    const periodEl = lineEl ? lineEl.closest('[data-period], [data-period-name], .marketBox_body, .marketBox') : marketBox;" + NL
        + "    const attrPeriodHint = periodEl ? cleanText(periodEl.getAttribute('data-period') || periodEl.getAttribute('data-period-name') || '') : '';" + NL
        + "    const groupedBody = lineEl && marketBox && marketBox.classList.contains('is-groupedMarket') ? lineEl.closest('.marketBox_body') : null;" + NL
        + "    const oddsItem = btn.closest('.marketBox_item'); const oddsList = oddsItem ? oddsItem.parentElement : null;" + NL
        + "    const columnIndex = oddsItem && oddsList && oddsList.classList.contains('marketBox_list') ? siblingIndex(oddsItem) : -1;" + NL
        + "    const columnHeaders = groupedBody ? Array.from(groupedBody.querySelectorAll('.marketBox_itemValue')).map(el => cleanText(el.innerText || el.textContent)).filter(Boolean) : [];" + NL
        + "    const columnHeading = columnIndex >= 0 && columnIndex < columnHeaders.length ? columnHeaders[columnIndex] : '';" + NL
        + "    const periodHint = attrPeriodHint || columnHeading;" + NL
        + "    const evidenceEl = lineEl || marketBox || btn;" + NL
        + "    const headingPath = [ancestorTitle, sectionTitle, marketTitle].filter(Boolean).join(' > ');" + NL
        + "    const scopeHint = evidenceEl.getAttribute('data-settlement-scope') || evidenceEl.getAttribute('data-scope') || '';" + NL
        + "    let lineHint = evidenceEl.getAttribute('data-line') || evidenceEl.getAttribute('data-handicap') || '';" + NL
        + "    if (!lineHint && sliderEl) lineHint = cleanText(getComputedStyle(sliderEl).getPropertyValue('--sliderTextValue')).replace(/^['\"]|['\"]$/g, '');" + NL
        + "    const handicapKind = /2-drożny|2-drozny/i.test(marketTitle) ? 'TWO_WAY' : (/handicap/i.test(marketTitle) ? 'THREE_WAY' : '');" + NL
        + "    const style = getComputedStyle(btn); const visibility = (style.display==='none'||style.visibility==='hidden'||style.opacity==='0') ? 'HIDDEN' : 'VISIBLE';" + NL
        + "    const renderState = evidenceEl.getAttribute('data-state') || evidenceEl.getAttribute('aria-hidden') || visibility;" + NL
        + "    let scrollParent=evidenceEl.parentElement; while(scrollParent&&scrollParent!==document.body){ const s=getComputedStyle(scrollParent); if(/(auto|scroll)/.test(s.overflowY+s.overflowX)) break; scrollParent=scrollParent.parentElement; }" + NL
        + "    const scrollPosition = scrollParent ? (scrollParent.scrollLeft+','+scrollParent.scrollTop) : '0,0';" + NL
        + "    const activeSubtab = cleanText((document.querySelector('[role=tab][aria-selected=true], .tab_item.isActive, .tab.isActive')||{}).innerText || '');" + NL
        + "    const containerPath = nodePath(marketBox || evidenceEl.parentElement); const rowEl = lineEl || evidenceEl.parentElement; const rowIndex = siblingIndex(rowEl); const cellPath = nodePath(btn);" + NL
        + "    const periodScopeId='scope:'+currentTabName.replace(/\\s+/g,'.')+'|'+containerPath+(columnHeading ? '|column:'+columnHeading.replace(/\\s+/g,'.') : ''); const periodEvidenceCandidates=[]; const addEvidence=(type,value)=>{const v=cleanText(value);if(/(?:1\\.\\s*połowa|2\\.\\s*połowa|cały\\s*mecz|90\\s*min)/i.test(v))periodEvidenceCandidates.push({source_type:type,raw_value:v,normalized_hint:v,dom_fingerprint:periodScopeId,evidence_period:'',evidence_provenance:type});}; addEvidence('ATTRIBUTE',attrPeriodHint);addEvidence('HEADER',columnHeading);addEvidence('CONTAINER',marketTitle);" + NL
        + "    const domPath = cellPath; const marketInstanceId = 'tab:'+currentTabName.replace(/\\s+/g,'.')+'|'+containerPath+(columnHeading ? '|column:'+columnHeading.replace(/\\s+/g,'.') : '')+'|row#'+rowIndex+'|cell:'+cellPath;" + NL
        + "    let sel = '';" + NL
        + "    let btnText = cleanText(btn.innerText || btn.textContent);" + NL
        + "    if (sliderSelectionLabel) {" + NL
        + "      sel = sliderSelectionLabel;" + NL
        + "    } else if (selectionLabel) {" + NL
        + "      sel = selectionLabel;" + NL
        + "    } else if (btnText) {" + NL
        + "      const fullMatch = btnText.match(/(.*?)(?:\\s+|^)([1-9]\\d{0,2}(?:[.,]\\d{1,2})?)(?:\\s+|$)/);" + NL
        + "      if (fullMatch && fullMatch[1].trim()) {" + NL
        + "        sel = fullMatch[1].trim();" + NL
        + "      }" + NL
        + "    }" + NL
        + "    if (!sel) {" + NL
        + "      sel = marketTitle || 'SELECTION';" + NL
        + "    }" + NL
        + "    let rawTxt = sliderEl ? [participantHint, sliderSelectionLabel, oddsVal].filter(Boolean).join(' ') : (selectionLabel ? (selectionLabel + ' ' + oddsVal) : (btnText || oddsVal)).trim();" + NL
        + "    results.push({" + NL
        + "      container_id: containerId," + NL
        + "      category: currentTabName," + NL
        + "      market: marketTitle," + NL
        + "      selection: sel," + NL
        + "      section_title: sectionTitle," + NL
        + "      ancestor_title: ancestorTitle," + NL
        + "      section_source: sectionContext.source," + NL
        + "      section_key: sectionContext.key," + NL
        + "      active_tab: currentTabName," + NL
        + "      active_subtab: activeSubtab," + NL
        + "      period_hint: periodHint," + NL
        + "      period_evidence_candidates: periodEvidenceCandidates, period_scope_id: periodScopeId," + NL
        + "      column_heading: columnHeading," + NL
        + "      settlement_scope_hint: scopeHint," + NL
        + "      participant_hint: participantHint," + NL
        + "      line_hint: lineHint," + NL
        + "      handicap_kind: handicapKind," + NL
        + "      market_instance_id: marketInstanceId," + NL
        + "      dom_path: domPath," + NL
        + "      heading_path: headingPath," + NL
        + "      box_context: marketBox ? cleanText(marketBox.innerText || marketBox.textContent).slice(0, 200) : ''," + NL
        + "      visibility: visibility," + NL
        + "      render_state: renderState," + NL
        + "      scroll_position: scrollPosition," + NL
        + "      odds: oddsVal," + NL
        + "      raw: rawTxt," + NL
        + "      missing_header: isMissingHeader," + NL
        + "      source_index: sourceIndex" + NL
        + "    });" + NL
        + "  }" + NL
        + "  return results;" + NL
        + "}"
    )
    return script


_capture_counter = itertools.count(1)


def _extract_dom_from_page(page: Any, tab_name: str) -> list[dict]:
    cap_id = f"cap_{next(_capture_counter)}"
    items = page.evaluate(_make_dom_script(), tab_name)
    for it in items:
        it["capture_id"] = cap_id
    return items


def _select_stable_tab_snapshot(dom_items: list[dict[str, Any]], visible_priced_count: int) -> list[dict[str, Any]]:
    """Prefer one complete stable capture over repeated render observations.

    The exhaustive crawler intentionally unions states so virtual scrollers are
    not lost.  A non-virtual tab can, however, expose the same physical
    controls during several crawler passes.  When one capture contains exactly
    the current visible priced-control count, it is the authoritative current
    view.  Retaining that one capture prevents price/render history from
    becoming additional raw propositions.  If no such complete capture exists,
    preserve the union: it is the evidence needed for virtualized content.
    """
    if visible_priced_count <= 0 or not dom_items:
        return dom_items
    by_capture: dict[str, list[dict[str, Any]]] = {}
    for item in dom_items:
        if str(item.get("record_type") or "ODD") != "ODD":
            continue
        capture_id = str(item.get("capture_id") or "")
        if capture_id:
            by_capture.setdefault(capture_id, []).append(item)
    matching = [(capture_id, items) for capture_id, items in by_capture.items()
                if len(items) == visible_priced_count]
    if not matching:
        return dom_items
    # Capture ids are monotonic (cap_N).  The latest complete state reflects
    # the final stable rendering and is deterministic even with retries.
    _, selected = max(matching, key=lambda pair: int(re.search(r"(\d+)$", pair[0]).group(1))
                       if re.search(r"(\d+)$", pair[0]) else -1)
    return selected


def _recover_zero_raw_priced_tab(extract_current: Callable[[], list[dict[str, Any]]],
                                 priced_count: int, attempts: int = 3) -> list[dict[str, Any]]:
    """Bounded active-panel fallback when the state crawler returned no rows.

    This is deliberately not a second scan.  It reads the already active panel
    only when browser metrics prove there are priced controls which would
    otherwise be silently lost.
    """
    if priced_count <= 0:
        return []
    for _ in range(max(1, attempts)):
        rows = extract_current()
        if rows:
            return rows
        time.sleep(0.15)
    return []


def _should_active_panel_fallback(tab_name: str, priced_count: int, dom_items: list[dict[str, Any]]) -> bool:
    """MyCombi has a dedicated bet-slip state path, never ordinary ODD fallback."""
    return (str(tab_name or "").strip().casefold() != "mycombi"
            and priced_count > 0 and not dom_items)


def _mycombi_normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def validate_mycombi_state_for_event(state: dict[str, Any], home_team: str, away_team: str,
                                     run_id: str = "", event_id: str = "", source_hash: str = "") -> dict[str, Any]:
    """Fail closed on a stale event-specific MyCombi component.

    Generic conditions are valid in any event.  A result-market component is
    event-specific and must be one of the current participants or a draw token;
    a single foreign component invalidates the generated combination as a whole.
    """
    home, away = _mycombi_normalize(home_team), _mycombi_normalize(away_team)
    rejected: list[dict[str, Any]] = []
    for component in state.get("components") or []:
        label, heading = _mycombi_normalize(component.get("label")), _mycombi_normalize(component.get("market_heading"))
        # Betclic appends an explicit handicap to otherwise exact team labels.
        # Remove only a terminal parenthetical line expression for event binding.
        team_label = re.sub(r"\s*\([+-]?\d+(?:[.,]\d+)?\)\s*$", "", label).strip()
        is_result = any(token in heading for token in ("wynik meczu", "1x2", "match result"))
        allowed_result = team_label in {home, away, "1", "2", "x", "remis", "draw"}
        if is_result and not allowed_result:
            rejected.append({"label": component.get("label") or "", "market_heading": component.get("market_heading") or "",
                             "reason": "MYCOMBI_FOREIGN_EVENT_COMPONENT", "run_id": run_id,
                             "event_id": event_id, "source_hash": source_hash})
    if rejected:
        return {"components": [], "combination": None, "price_fingerprints": state.get("price_fingerprints") or [], "rejected": rejected,
                "status": "CROSS_EVENT_MYCOMBI"}
    for component in state.get("components") or []:
        component.update({"run_id": run_id, "event_id": event_id, "source_hash": source_hash})
    combination = state.get("combination")
    if combination:
        combination.update({"run_id": run_id, "event_id": event_id, "source_hash": source_hash})
    return {**state, "rejected": [], "status": "ACTIVE_CURRENT_STATE"}


def _canonicalize_mycombi_component(component: dict[str, Any], home_team: str, away_team: str) -> dict[str, Any]:
    """Canonicalize one selected, unpriced MyCombi condition from the bet slip."""
    label = str(component.get("label") or "").strip()
    heading = str(component.get("market_heading") or "").strip()
    combined = f"{heading} {label}"
    normalized = _mycombi_normalize(combined)
    home, away = _mycombi_normalize(home_team), _mycombi_normalize(away_team)
    if home and home in normalized:
        owner = "HOME"
    elif away and away in normalized:
        owner = "AWAY"
    elif any(token in normalized for token in ("zawodnik", "strzelec", "player")):
        owner = "PLAYER"
    elif heading:
        owner = "MATCH"
    else:
        owner = "UNKNOWN"
    # Keep the component's own market family: using the synthetic MYCOMBI
    # family here bypassed the existing canonical full-match market evidence.
    family, _ = classify_family(heading, label, "", home_team, away_team)
    parsed_period, period_source, period_confidence = classify_period_detail(
        heading, "", "", "", "MyCombi", family
    )
    period = {"FULL_TIME": "FT", "1ST_HALF": "1H", "2ND_HALF": "2H"}.get(parsed_period, "UNKNOWN")
    line_match = re.search(r"(?<!\d)([-+]?\d+[,.]\d+)(?!\d)", combined)
    line = line_match.group(1).replace(",", ".") if line_match else None
    settlement = (
        "REGULAR_TIME" if any(token in normalized for token in ("wyłączeniem dogrywki", "wylaczeniem dogrywki", "reg. czas", "regular time"))
        else {"FT": "FULL_TIME", "1H": "FIRST_HALF", "2H": "SECOND_HALF"}.get(period, "UNKNOWN")
    )
    semantic = "|".join((_mycombi_normalize(heading), _mycombi_normalize(label), owner, period,
                           str(line or ""), settlement))
    component_id = "mc_" + hashlib.sha256(semantic.encode("utf-8")).hexdigest()[:20]
    return {
        "component_id": component_id,
        "label": label,
        "market_heading": heading,
        "owner": owner,
        "period": period,
        "period_source": period_source,
        "period_confidence": period_confidence,
        "line": line,
        "settlement": settlement,
        "display_order": int(component.get("display_order") or 0),
        "selected": True,
        "individual_odds": None,
        "native_selection_id": str(component.get("native_selection_id") or ""),
        "source": "BETCLIC_MYCOMBI_COMPONENT",
    }


def _extract_mycombi_state(page: Any, home_team: str, away_team: str) -> dict[str, Any]:
    """Read the current MyCombi bet-slip state; components are never assigned odds."""
    script = """() => {
      const text=e=>(e?.innerText||e?.textContent||'').replace(/\\s+/g,' ').trim();
      const path=e=>{const out=[];for(let n=e;n&&n!==document.body;n=n.parentElement){const i=n.parentElement?Array.prototype.indexOf.call(n.parentElement.children,n):0;out.push((n.tagName||'').toLowerCase()+'['+(n.className||'')+'#'+i+']');}return out.reverse().join('>');};
      const decimal=e=>{const m=text(e).match(/([1-9]\\d{0,2}(?:[,.]\\d{1,2})?)/);return m?m[1].replace(',','.'):'';};
      const card=document.querySelector('betting-slip-selection-card .progressiveBettingSlip_cardMarket.is-betbuilder');
      if(!card)return {components:[],combined_odds:'',representations:[]};
      const cardRoot=card.closest('betting-slip-selection-card');
      const components=Array.from(card.querySelectorAll('betting-slip-selection-card-combo li.list_item')).map((li,index)=>({
        label:text(li.querySelector('.list_itemTitle')),market_heading:text(li.querySelector('.list_itemSubtitle')),
        display_order:index+1,native_selection_id:li.getAttribute('data-selection-id')||li.getAttribute('data-id')||''
      })).filter(x=>x.label&&x.market_heading);
      const combined_odds=decimal(cardRoot?.querySelector('betting-slip-odds-field button.is-readonly, button.is-odd.is-readonly'));
      const representations=Array.from(document.querySelectorAll('sports-betting-slip button.is-odd.is-readonly')).filter(btn=>decimal(btn)===combined_odds).map(btn=>({odds:decimal(btn),dom_path:path(btn)}));
      return {components,combined_odds,representations};
    }"""
    try:
        captured = page.evaluate(script)
    except Exception:
        return {"components": [], "combination": None, "price_fingerprints": []}
    components = [_canonicalize_mycombi_component(item, home_team, away_team)
                  for item in (captured.get("components") or [])]
    if not components or not captured.get("combined_odds"):
        return {"components": components, "combination": None, "price_fingerprints": captured.get("representations") or []}
    component_ids = sorted(component["component_id"] for component in components)
    event_identity = _mycombi_normalize(f"{home_team}|{away_team}")
    combination_id = "mcb_" + hashlib.sha256((event_identity + "|" + "|".join(component_ids)).encode("utf-8")).hexdigest()[:20]
    return {
        "components": components,
        "combination": {
            "combination_id": combination_id,
            "components": component_ids,
            "component_count": len(components),
            "combined_odds": str(captured["combined_odds"]),
            "source": "BETCLIC_MYCOMBI_GENERATED_PRICE",
            "ui_representation_count": len(captured.get("representations") or []),
            "status": "ACTIVE_CURRENT_STATE",
        },
        "price_fingerprints": captured.get("representations") or [],
    }


def _mycombi_state_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Represent the current MyCombi state in raw JSONL without ordinary odds rows."""
    rows: list[dict[str, Any]] = []
    for component in state.get("components") or []:
        rows.append({
            "record_type": "MYCOMBI_COMPONENT", "category": "MyCombi", "market": component["market_heading"],
            "selection": component["label"], "odds": "", "raw": component["label"],
            "mycombi_component": component, "period_hint": component["period"],
            "period_source": component["period_source"], "period_confidence": component["period_confidence"],
            "line_hint": component["line"] or "",
            "settlement_scope_hint": component["settlement"], "market_instance_id": component["component_id"],
        })
    combination = state.get("combination")
    if combination:
        rows.append({
            "record_type": "MYCOMBI_COMBINATION", "category": "MyCombi", "market": "MyCombi",
            "selection": "MyCombi", "odds": combination["combined_odds"], "raw": combination["combined_odds"],
            "mycombi_combination": combination, "market_instance_id": combination["combination_id"],
        })
    return rows


class BetclicOddsExtractor:
    def __init__(
        self,
        progress_callback: Callable[[float, str], None] | None = None,
        diag: DiagnosticsManager | None = None
    ) -> None:
        self.progress_callback = progress_callback
        self.diag = diag or DiagnosticsManager()

    def _notify_stage(self, percent: float, stage_msg: str) -> None:
        self.diag.log(stage_msg)
        if self.progress_callback:
            try:
                self.progress_callback(percent, stage_msg)
            except Exception:
                pass

    def extract(self, url: str, max_scan_seconds: float = DEFAULT_RUN_MAX_SECONDS) -> dict[str, Any]:
        run_start_time = time.time()
        capture_started_at = utc_now_rfc3339()
        run_max_seconds = max_scan_seconds
        run_deadline = run_start_time + run_max_seconds

        self.diag.log(f"BUILD_ID={BUILD_ID}")
        self.diag.log(f"Starting extraction for URL: {url}")

        is_valid, err_msg = validate_betclic_url(url)
        if not is_valid:
            return {"status": "BŁĄD", "error": err_msg, "packet_text": "",
                    "odds_count": 0, "market_count": 0, "market_group_count": 0, "unresolved_count": 0}

        # Stage 1: Playwright import
        self._notify_stage(0.05, "PLAYWRIGHT_IMPORT_START")
        try:
            from playwright.sync_api import Page, sync_playwright
            from playwright_stealth import Stealth
            self._notify_stage(0.1, "PLAYWRIGHT_IMPORT_OK")
        except BaseException as exc:
            self.diag.log(f"PLAYWRIGHT_IMPORT_FAILED: {exc}")
            return {"status": "BŁĄD", "error": f"Brak biblioteki Playwright: {exc}",
                    "packet_text": "", "odds_count": 0, "market_count": 0, "market_group_count": 0, "unresolved_count": 0}

        run_id = f"run_{int(time.time())}_{os.getpid()}"
        raw_before_dedupe: list[dict[str, Any]] = []
        history_observation_seeds: list[tuple[dict[str, Any], str, int]] = []
        route_event_id = parse_betclic_route_event_id(url)
        embedded_provider_info: dict[str, Any] = {
            "provider_match_id": None, "match_date_utc": None, "is_live": None,
        }
        captured_page_html = ""
        native_team_names = {}
        transport_listener = None
        page = None
        transport_drain_attempted = False

        def drain_provider_transport_listener() -> None:
            nonlocal transport_drain_attempted
            if transport_listener is None or page is None or transport_drain_attempted:
                return
            # A Playwright Page is only usable while its BrowserContext and
            # event loop are alive.  Drain at most once before shutdown; the
            # later history flush must use only the evidence already buffered
            # by the passive listener.
            transport_drain_attempted = True
            remaining_ms = max(0, int((run_deadline - time.time()) * 1000))
            try:
                pending = transport_listener.drain(page, min(PROVIDER_TRANSPORT_DRAIN_MS, remaining_ms))
                if pending:
                    self.diag.log(f"HISTORY_PROVIDER_TRANSPORT_V0_1_PENDING_AFTER_DRAIN={pending}")
            except Exception as drain_exc:
                self.diag.log("HISTORY_PROVIDER_TRANSPORT_V0_1_DRAIN_FAILED:" + format_transport_exception(drain_exc))

        def flush_provider_transport_for_exact_bridge() -> None:
            """Flush buffered response evidence on every terminal path, not only prematch success."""
            drain_provider_transport_listener()
            log_provider_transport_listener_errors(self.diag, transport_listener)
            if transport_listener is None or not route_event_id or not captured_page_html:
                return
            try:
                try:
                    bridge = build_provider_derived_bridge(route_event_id, captured_page_html,
                        f"history_v0_1/hydration/run_{run_id}", capture_started_at)
                except IdentityBridgeValidationError:
                    bridge = load_exact_persisted_bridge(
                        HISTORY_IDENTITY_BRIDGE_V0_1_DIR, route_event_id,
                    )
                    self.diag.log(f"HISTORY_IDENTITY_BRIDGE_V0_1_REUSED={bridge['bridge_sha256']}")
                try:
                    write_bridge_append_only(HISTORY_IDENTITY_BRIDGE_V0_1_DIR, bridge)
                except FileExistsError:
                    pass
                records = transport_listener.flush(HISTORY_PROVIDER_TRANSPORT_V0_1_DIR, bridge)
                self.diag.log(f"HISTORY_PROVIDER_TRANSPORT_V0_1_COUNT={len(records)}")
                log_provider_transport_flush_summary(self.diag, transport_listener)
            except Exception as transport_exc:
                self.diag.log(f"HISTORY_PROVIDER_TRANSPORT_V0_1_FLUSH_FAILED:{format_transport_exception(transport_exc)}")

        def write_history_capture_failed() -> None:
            """Persist attempted captures without affecting legacy failure handling."""
            try:
                capture_finished_at = utc_now_rfc3339()
                write_history_sidecars(HISTORY_V0_1_DIR, {
                    "schema_version": "APEX_HISTORY_COLLECTION_CONTRACT_V0_1",
                    "run_id": run_id, "provider": "BETCLIC", "provider_event_id": None,
                    "source_url": url, "kickoff_at": None, "kickoff_timezone": "UTC",
                    "kickoff_source": None, "capture_started_at": capture_started_at,
                    "capture_finished_at": capture_finished_at, "capture_clock_timezone": "UTC",
                    "provider_is_live": None, "preflight_status": "UNKNOWN",
                    "capture_status": "CAPTURE_FAILED",
                    "identity_validation": {"route_event_id": route_event_id,
                                            "embedded_match_id": None, "exact_match": False},
                }, [])
            except Exception as history_exc:
                self.diag.log(f"HISTORY_V0_1_SIDECAR_WRITE_FAILED: {type(history_exc).__name__}")
        tab_html_count = 0
        tab_screenshot_count = 0
        evidence_errors = 0
        source_idx = 0
        capture_source_parts: dict[str, bytes] = {}

        extracted_odds: list[dict[str, str]] = []
        unresolved_items: list[dict[str, str]] = []
        mycombi_components: list[dict[str, Any]] = []
        mycombi_combination: dict[str, Any] | None = None
        mycombi_rejection_ledger: list[dict[str, Any]] = []
        candidate_ledger: list[dict[str, Any]] = []
        scanned_tabs: list[str] = []
        coverage_manifests: list[dict[str, Any]] = []
        tab_reports: list[dict[str, Any]] = []
        match_str = comp_str = kickoff_str = home_team = away_team = ""

        context = None
        pw_cm = None

        try:
            pw_cm = sync_playwright()
            p = pw_cm.__enter__()

            chrome_exe = find_chrome_exe()

            self._notify_stage(0.12, "BROWSER_LAUNCH_START")

            if chrome_exe:
                # Launch persistent context with user's installed Google Chrome
                self.diag.log(f"Launching persistent Chrome: {chrome_exe}")
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    executable_path=chrome_exe,
                    headless=False,
                    channel=None,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-infobars",
                    ],
                    viewport={"width": 1366, "height": 900},
                    ignore_https_errors=True,
                )
            else:
                # Fallback: launch Playwright's bundled Chromium with persistent profile
                self.diag.log("Chrome not found, launching bundled Chromium.")
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    viewport={"width": 1366, "height": 900},
                    ignore_https_errors=True,
                )

            self._notify_stage(0.18, "BROWSER_LAUNCH_OK")

            page = context.pages[0] if context.pages else context.new_page()
            # Register before navigation: no interception, cookies, or headers
            # are read; candidate bytes remain memory-only until an exact bridge
            # is available at end of capture.
            transport_listener = PassiveBetclicTransportListener(
                context, run_id=run_id, source_page_url=url, route_event_id=route_event_id,
            )
            # Unit tests supply a MagicMock page.  MagicMock claims every
            # attribute exists, which makes playwright-stealth report a false
            # duplicate-application warning.  Production always supplies a
            # concrete Playwright Page, so keep the anti-detection setup there.
            if isinstance(page, Page):
                try:
                    Stealth().apply_stealth_sync(page)
                except Exception as stealth_exc:
                    self.diag.log(f"STEALTH_APPLICATION_FAILED: {stealth_exc}")

            self._notify_stage(0.22, "PAGE_READY")

            # Stage 2: Navigate
            self._notify_stage(0.28, "NAVIGATION_START")
            nav_status = 200
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                if response:
                    nav_status = response.status
                self.diag.log(f"Navigation HTTP status: {nav_status}")
            except BaseException as nav_exc:
                err_msg = f"NAVIGATION_FAILED: {nav_exc}"
                self.diag.log(err_msg)
                write_history_capture_failed()
                return {"status": "BŁĄD", "error_code": "NAVIGATION_TIMEOUT", "error": err_msg,
                        "packet_text": "", "odds_count": 0, "market_count": 0, "market_group_count": 0, "unresolved_count": 0}

            time.sleep(4.0)
            self._notify_stage(0.33, f"NAVIGATION_RESULT status={nav_status}")

            # 403 / WAF / bot-detection rejection
            title = page.title()
            self.diag.log(f"Page title: '{title}'")
            title_low = title.lower()

            if nav_status in (401, 403, 429) or any(b in title_low for b in [
                    "403 forbidden", "error 403", "access denied", "cloudflare", "just a moment"]):
                err_msg = "Betclic zablokował sesję (403 / WAF). Uruchom aplikację, poczekaj aż Chrome załaduje Betclic i zaakceptuje cookies, następnie spróbuj ponownie."
                self.diag.log(f"BETCLIC_FORBIDDEN: {err_msg}")
                write_history_capture_failed()
                return {"status": "BŁĄD", "error_code": "BETCLIC_FORBIDDEN", "error": err_msg,
                        "packet_text": "", "odds_count": 0, "market_count": 0, "market_group_count": 0, "unresolved_count": 0}

            # Cookie banner
            if not url.startswith("file://"):
                for sel in [
                    "#popin_tc_privacy_button_2",
                    "button[id*='privacy']",
                    "button:has-text('AKCEPTUJĘ')",
                    "button:has-text('Akceptuję')",
                    "button:has-text('Zgadzam się')",
                    "button:has-text('Accept')",
                ]:
                    try:
                        btn = page.query_selector(sel)
                        if btn and btn.is_visible():
                            btn.click()
                            time.sleep(0.8)
                            break
                    except Exception:
                        pass

                dismiss_known_betclic_overlays(page, self.diag.log)

            # Metadata
            if not any(b in title_low for b in ["error", "403", "forbidden", "access denied"]):
                match_m = re.search(r"Obstawianie\s+(.+?)\s+\||^([^-]+-[^-]+)", title)
                if match_m:
                    match_str = (match_m.group(1) or match_m.group(2)).strip()
                if not match_str:
                    match_str = title.split("|")[0].replace("Obstawianie", "").strip()
                if " - " in match_str:
                    parts = match_str.split(" - ", 1)
                    home_team = clean_team_name(parts[0])
                    away_team = clean_team_name(parts[1])
                comp_m = re.search(r"Bukmacher\s+([^|]+)", title)
                if comp_m:
                    comp_str = comp_m.group(1).strip()

            # Scope the selector to the match scoreboard; generic date selectors can
            # select a sidebar/live-event value or an empty date placeholder.
            kickoff_visible = ""
            for selector in ("sports-match-page-desktop .scoreboard_hour", ".scoreboard_hour", "sports-match-page-desktop time"):
                kickoff_el = page.query_selector(selector)
                if kickoff_el and kickoff_el.is_visible():
                    kickoff_visible = kickoff_el.inner_text().strip()
                    if kickoff_visible:
                        break
            kickoff_str, kickoff_source = extract_current_event_kickoff("", kickoff_visible)

            try:
                captured_page_html = page.content()
                from team_name_evidence import extract_native_team_names
                native_team_names = extract_native_team_names(captured_page_html, home_team, away_team, route_event_id)
                embedded_provider_info = extract_embedded_provider_match_info(captured_page_html)
            except Exception:
                embedded_provider_info = {
                    "provider_match_id": None, "match_date_utc": None, "is_live": None,
                }

            preflight_status, preflight_proof, preflight_seconds = _preflight_event_status(page)
            self.diag.log(f"PREFLIGHT status={preflight_status} proof='{preflight_proof}' seconds={preflight_seconds}")
            self.diag.save_dom_json({"preflight_status": preflight_status, "proof": preflight_proof,
                                     "seconds": preflight_seconds})
            if preflight_status != "PREMATCH":
                capture_finished_at = utc_now_rfc3339()
                history_status = evaluate_capture_status(
                    route_event_id, embedded_provider_info, preflight_status,
                    capture_started_at, capture_finished_at,
                )
                try:
                    write_history_sidecars(HISTORY_V0_1_DIR, {
                        "schema_version": "APEX_HISTORY_COLLECTION_CONTRACT_V0_1",
                        "run_id": run_id, "provider": "BETCLIC",
                        "provider_event_id": history_status["provider_event_id"], "source_url": url,
                        "kickoff_at": history_status["kickoff_at"], "kickoff_timezone": "UTC",
                        "kickoff_source": "BETCLIC_EMBEDDED_MATCH_DATE_UTC",
                        "capture_started_at": capture_started_at, "capture_finished_at": capture_finished_at,
                        "capture_clock_timezone": "UTC", "provider_is_live": history_status["provider_is_live"],
                        "preflight_status": preflight_status, "capture_status": history_status["capture_status"],
                        "identity_validation": {"route_event_id": route_event_id,
                                                "embedded_match_id": history_status["embedded_match_id"],
                                                "exact_match": history_status["exact_match"]},
                    }, [])
                except Exception as history_exc:
                    self.diag.log(f"HISTORY_V0_1_SIDECAR_WRITE_FAILED: {type(history_exc).__name__}")
                flush_provider_transport_for_exact_bridge()
                return {"status": "BLOCKED", "error_code": "EVENT_NOT_PREMATCH",
                        "error": _EVENT_STATUS_MESSAGES.get(preflight_status, f"Event status is {preflight_status}"),
                        "event_status": preflight_status,
                        "preflight_proof": preflight_proof, "preflight_seconds": preflight_seconds,
                        "packet_text": "", "odds_count": 0, "market_count": 0,
                        "market_group_count": 0, "unresolved_count": 0}

            is_live = False
            event_status = "GOTOWE"
            self.diag.log(f"EVENT_STATUS: {event_status} (preflight='{preflight_proof}')")

            # Stage 3: Detect and iterate market tabs
            self._notify_stage(0.38, "TAB_DETECTION_START")

            tab_selectors = [
                # CONFIRMED from real Betclic DOM snapshot:
                # Market category tabs are div.tab_item[data-qa="tab-btn"] inside div.tab.isPrimary
                "div.tab.isPrimary div.tab_item[data-qa='tab-btn']",
                # Fallbacks in case class changes
                "div.tab_item[data-qa='tab-btn']",
                "[data-qa='tab-btn']",
            ]
            detected_tabs: list[tuple[str, Any]] = []

            for sel in tab_selectors:
                if detected_tabs:
                    break
                try:
                    tabs = page.query_selector_all(sel)
                    for t in tabs:
                        try:
                            if not t.is_visible():
                                continue
                            # Get text from span.tab_label child if present, else innerText
                            label_el = t.query_selector("span.tab_label")
                            if label_el:
                                txt = label_el.inner_text().strip()
                            else:
                                txt = t.inner_text().strip().replace("\n", " ")
                            txt = txt.strip()
                            if txt and 1 < len(txt) < 30 and txt not in [dt[0] for dt in detected_tabs]:
                                detected_tabs.append((txt, t))
                        except Exception:
                            pass
                except Exception:
                    pass

            # MyCombi is Betclic's bet builder: in every live capture (12 matches,
            # 2026-09-28..10-02) it held no market odds yet cost up to 13 s.  Its
            # offers are built from the markets of the other tabs, so it is not
            # scanned (user request 2026-10-02).
            skipped_tabs = [name for name, _ in detected_tabs if _is_bet_builder_tab(name)]
            detected_tabs = [(name, elem) for name, elem in detected_tabs if not _is_bet_builder_tab(name)]
            if skipped_tabs:
                self.diag.log(f"Skipped bet-builder tabs: {skipped_tabs}")

            if not detected_tabs:
                detected_tabs = [("GŁÓWNE", None)]

            self.diag.log(f"Detected tabs: {[t[0] for t in detected_tabs]}")

            detected_tab_names = [t[0] for t in detected_tabs]
            scanned_tabs: list[str] = []
            tab_reports: list[dict[str, Any]] = []
            unscanned_tabs: list[str] = []

            for tab_idx, (tab_name, tab_elem) in enumerate(detected_tabs):
                if time.time() >= run_deadline:
                    self.diag.log(f"RUN_DEADLINE reached ({run_max_seconds}s), marking remaining tabs as unscanned")
                    unscanned_tabs.extend([t[0] for t in detected_tabs[tab_idx:]])
                    break

                tab_start_time = time.time()
                tab_deadline = min(tab_start_time + 60.0, run_deadline)

                p_prog = 0.38 + (tab_idx / max(len(detected_tabs), 1)) * 0.45
                self._notify_stage(p_prog, f"SCANNING TAB: {tab_name}")

                tab_activation_ok = True
                tab_exception = None
                tab_unresolved_before = len(unresolved_items)

                # Click tab
                if tab_elem:
                    try:
                        # This onboarding dialog can appear after page readiness.
                        dismiss_known_betclic_overlays(page, self.diag.log)
                        link_el = tab_elem.query_selector("span.tab_link")
                        click_target = link_el if link_el else tab_elem
                        click_target.click()
                        # Wait up to 3s for isActive class
                        for _ in range(15):
                            time.sleep(0.2)
                            try:
                                cls = tab_elem.get_attribute("class") or ""
                                if "isActive" in cls or "is-active" in cls or "active" in cls:
                                    break
                            except Exception:
                                break
                    except Exception as te:
                        self.diag.log(f"Tab click failed '{tab_name}': {te}")
                        unresolved_items.append({"MARKET": f"TAB_{tab_name}", "RAW": tab_name, "REASON": "TAB_LOAD_FAILED"})
                        tab_activation_ok = False
                        tab_exception = "TAB_LOAD_FAILED"

                if not tab_activation_ok:
                    tab_seconds = round(time.time() - tab_start_time, 1)
                    t_status, t_reason = _evaluate_tab_status({
                        "tab_name": tab_name,
                        "activation_ok": False,
                        "interactive_control_count": 0,
                        "priced_candidate_count": 0,
                        "unpriced_control_count": 0,
                        "selectable_count": 0,
                        "raw_dom_items": 0,
                        "parsed_odds_count": 0,
                        "unresolved_count": 1,
                        "remaining_closed": 0,
                        "remaining_more": 0,
                        "deadline_hit": False,
                        "tab_seconds": tab_seconds,
                    })
                    tab_reports.append({
                        "tab_name": tab_name,
                        "status": t_status,
                        "reason": t_reason,
                        "interactive_control_count": 0,
                        "priced_candidate_count": 0,
                        "unpriced_control_count": 0,
                        "selectable_count": 0,
                        "raw_dom_items": 0,
                        "parsed_odds_count": 0,
                        "unresolved_count": 1,
                        "remaining_closed": 0,
                        "remaining_more": 0,
                        "deadline_hit": False,
                        "tab_seconds": tab_seconds,
                    })
                    continue

                scanned_tabs.append(tab_name)

                # Stateful union capture keeps virtualized rows, nested scroll
                # content, sub-tabs and accordion states without clicking odds.
                try:
                    mycombi_rejected_this_tab: list[dict[str, Any]] = []
                    crawler = ExhaustiveStateCrawler(page, _extract_dom_from_page, tab_deadline, self.diag.log)
                    dom_data, manifest = crawler.crawl_tab(tab_name)
                    if not dom_data and tab_elem and tab_name.strip().casefold() != "mycombi":
                        # A visible market tab that stayed empty is re-opened
                        # once before the capture may call it empty.
                        self.diag.log(f"EMPTY_TAB_RETRY tab '{tab_name}'")
                        try:
                            (tab_elem.query_selector("span.tab_link") or tab_elem).click()
                            time.sleep(1.5)
                            dom_data, manifest = ExhaustiveStateCrawler(
                                page, _extract_dom_from_page, tab_deadline, self.diag.log).crawl_tab(tab_name)
                        except Exception as retry_exc:
                            self.diag.log(f"EMPTY_TAB_RETRY_FAILED tab '{tab_name}': {retry_exc}")
                    # The persistent bet-slip is rendered beside every tab.  It is
                    # application state, not a market row of the currently scanned
                    # tab; collect its canonical MyCombi state only below.
                    dom_data = [item for item in dom_data
                                if "sports-betting-slip" not in str(item.get("dom_path") or "")]
                    if tab_name.strip().casefold() == "mycombi":
                        # The two readonly price buttons in the bet slip are UI copies,
                        # not two market odds.  Preserve only the active semantic state.
                        state = validate_mycombi_state_for_event(
                            _extract_mycombi_state(page, home_team, away_team), home_team, away_team,
                            run_id, f"{home_team}|{away_team}", "",
                        )
                        for rejected in state.get("rejected") or []:
                            self.diag.log("MYCOMBI_FOREIGN_EVENT_COMPONENT=" + json.dumps(rejected, ensure_ascii=False))
                        mycombi_rejected_this_tab = list(state.get("rejected") or [])
                        mycombi_rejection_ledger.extend(mycombi_rejected_this_tab)
                        if mycombi_rejected_this_tab:
                            for representation in state.get("price_fingerprints") or []:
                                evidence_path = representation.get("dom_path") or ""
                                candidate_ledger.append({"run_id":run_id,"event_id":f"{home_team}|{away_team}","source_hash":"","tab":tab_name,
                                    "container_id":"sports-betting-slip","row_id":"","column_id":"","native_selection_id":evidence_path,
                                    "evidence_reference":evidence_path,"odds":representation.get("odds") or "",
                                    "foreign_event":"Novorizontino SP - Juventude RS",
                                    "current_event":f"{home_team} - {away_team}",
                                    "terminal_state":"FOREIGN","reason":"FOREIGN_EVENT_BET_SLIP_REPRESENTATION"})
                        mycombi_components = state["components"]
                        mycombi_combination = state["combination"]
                        dom_data.extend(_mycombi_state_rows(state))
                        if state["price_fingerprints"]:
                            self.diag.log("MYCOMBI_GENERATED_PRICE_UI_REPRESENTATIONS=" + json.dumps(state["price_fingerprints"], ensure_ascii=False))
                    if tab_name == "Strzelcy" and manifest.finished_scroll_containers < manifest.scroll_containers:
                        retry_evidence = _retry_unfinished_strzelcy_containers(
                            page, lambda tab=tab_elem: tab.click() if tab else None, self.diag.log
                        )
                        dom_data.extend(_extract_dom_from_page(page, tab_name))
                        if retry_evidence and all(item["finished"] for item in retry_evidence):
                            manifest.finished_scroll_containers = manifest.scroll_containers
                    coverage_manifests.append(manifest.as_dict())
                    self.diag.log(f"Tab '{tab_name}': {len(dom_data)} raw DOM items across UI states")
                except Exception as dom_exc:
                    self.diag.log(f"EXHAUSTIVE_CRAWLER_ERROR tab '{tab_name}': {dom_exc}")
                    tab_exception = str(dom_exc)
                    dom_data = []

                # Capture per-tab HTML snapshot and screenshot after traversal.
                safe_name = _safe_tab_name(tab_name, tab_idx)
                html_file = SNAPSHOTS_DIR / f"tab_{run_id}_{tab_idx}_{safe_name}.html"
                png_file = DIAGNOSTICS_DIR / f"tab_{run_id}_{tab_idx}_{safe_name}.png"

                try:
                    html_file.write_text(page.content(), encoding="utf-8")
                    tab_html_count += 1
                except Exception as err:
                    evidence_errors += 1
                    self.diag.log(f"EVIDENCE_ERROR HTML '{tab_name}': {err}")

                try:
                    page.screenshot(path=str(png_file), full_page=True)
                    tab_screenshot_count += 1
                except Exception as err:
                    evidence_errors += 1
                    self.diag.log(f"EVIDENCE_ERROR Screenshot '{tab_name}': {err}")

                m_dom = _get_dom_expansion_metrics(page, tab_name)
                tab_interactive = m_dom.get("interactive_control_count", 0)
                tab_priced = m_dom.get("priced_candidate_count", 0)
                tab_unpriced = m_dom.get("unpriced_control_count", 0)
                tab_selectable = m_dom.get("selectable_count", 0)
                tab_closed = m_dom.get("remaining_closed", 0)
                tab_more = m_dom.get("remaining_more", 0)
                tab_deadline_hit = time.time() >= tab_deadline

                if _should_active_panel_fallback(tab_name, tab_priced, dom_data):
                    dom_data = _recover_zero_raw_priced_tab(
                        lambda captured_tab_name=tab_name: _extract_dom_from_page(page, captured_tab_name), tab_priced
                    )
                    if dom_data:
                        self.diag.log(
                            f"TAB_ACTIVE_PANEL_FALLBACK tab='{tab_name}' "
                            f"priced={tab_priced} raw={len(dom_data)}"
                        )

                stable_dom_data = _select_stable_tab_snapshot(dom_data, tab_priced)
                if len(stable_dom_data) != len(dom_data):
                    self.diag.log(
                        f"TAB_RENDER_HISTORY_SUPPRESSED tab='{tab_name}' "
                        f"union={len(dom_data)} current={len(stable_dom_data)}"
                    )
                    dom_data = stable_dom_data

                tab_raw_dom = len(dom_data)
                capture_source_parts[f"{tab_idx:04d}:{tab_name}"] = json.dumps(
                    dom_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")

                for item in dom_data:
                    if native_team_names:
                        item["native_team_names"] = native_team_names
                    source_idx += 1
                    raw_record_id = f"{run_id}:{source_idx}"
                    event_id = f"{home_team}|{away_team}"
                    raw_observation = {
                        "native_team_names": item.get("native_team_names") or {},
                        "tab_name": tab_name,
                        "tab_index": tab_idx,
                        "market": item.get("market") or "",
                        "selection": item.get("selection") or "",
                        "odds": item.get("odds") or "",
                        "raw": item.get("raw") or "",
                        "category": item.get("category") or tab_name,
                        "period": classify_period(item.get("market") or "", item.get("section_title") or "", item.get("period_hint") or "", item.get("ancestor_title") or ""),
                        "market_instance_id": item.get("market_instance_id") or "",
                        "dom_path": item.get("dom_path") or "",
                        "heading_path": item.get("heading_path") or "",
                        "section_title": item.get("section_title") or "",
                        "ancestor_title": item.get("ancestor_title") or "",
                        "section_source": item.get("section_source") or "",
                        "section_key": item.get("section_key") or "",
                        "active_tab": item.get("active_tab") or tab_name,
                        "active_subtab": item.get("active_subtab") or "",
                        "period_hint": item.get("period_hint") or "",
                        "column_heading": item.get("column_heading") or "",
                        "settlement_scope_hint": item.get("settlement_scope_hint") or "",
                        "participant_hint": item.get("participant_hint"),
                        "line_hint": item.get("line_hint") or "",
                        "handicap_kind": item.get("handicap_kind") or "",
                        "visibility": item.get("visibility") or "",
                        "render_state": item.get("render_state") or "",
                        "scroll_position": item.get("scroll_position") or "",
                        "record_type": item.get("record_type") or "ODD",
                        "mycombi_component": item.get("mycombi_component"),
                        "mycombi_combination": item.get("mycombi_combination"),
                        "source_index": source_idx,
                        "capture_id": item.get("capture_id") or "",
                        "run_id": run_id, "event_id": event_id, "source_hash": "",
                        "raw_record_id": raw_record_id, "source_raw_record_ids": [raw_record_id],
                        "period_evidence_candidates": [{
                            **x, "raw_record_id": raw_record_id, "run_id": run_id, "event_id": event_id,
                            "source_hash": "", "evidence_period": classify_period_evidence(x)[0],
                            "evidence_period_reason": classify_period_evidence(x)[1],
                        } for x in (item.get("period_evidence_candidates") or [])],
                        "period_scope_id": item.get("period_scope_id") or "",
                    }
                    raw_before_dedupe.append(raw_observation)
                    history_observation_seeds.append((raw_observation, utc_now_rfc3339(), source_idx))
                    ledger_entry = {"run_id":run_id,"event_id":event_id,"source_hash":"","tab":tab_name,
                                    "container_id":item.get("container_id") or "","row_id":item.get("row_id") or "",
                                    "column_id":item.get("column_heading") or "","native_selection_id":item.get("native_selection_id") or raw_record_id,
                                    "raw_record_id":raw_record_id,"source_raw_record_ids":[raw_record_id],"terminal_state":"UNACCOUNTED_FAILURE"}
                    candidate_ledger.append(ledger_entry)

                    if item.get("record_type") in {"MYCOMBI_COMPONENT", "MYCOMBI_COMBINATION"}:
                        ledger_entry["terminal_state"] = "PASSIVE_NON_ODD"
                        continue

                    if item.get("accounted_exclusion_reason"):
                        ledger_entry["terminal_state"] = "ACCOUNTED_EXCLUDED_WITH_REASON"
                        ledger_entry["reason"] = item["accounted_exclusion_reason"]
                        continue

                    headerless_recovery = None
                    if item.get("missing_header"):
                        headerless_recovery = recover_headerless_top_offer(
                            item.get("selection") or "", tab_name,
                            item.get("market_instance_id") or "",
                            home_team, away_team,
                        )
                        if headerless_recovery is None:
                            headerless_recovery = headerless_top_card_exclusion(
                                item.get("selection") or "", tab_name, item.get("market_instance_id") or "")
                        if headerless_recovery is None:
                            ledger_entry["terminal_state"] = "ACCOUNTED_EXCLUDED_WITH_REASON"
                            unresolved_items.append({
                                "MARKET": f"NO_HEADER_{tab_name}",
                                "RAW": item.get("raw") or "",
                                "REASON": "MISSING_MARKET_HEADER",
                                "CONTAINER_ID": item.get("container_id") or ""
                            })
                            continue

                    odd_rec, unres_rec = parse_market_record(
                        native_team_names=item.get("native_team_names"),
                        category=item.get("category") or tab_name,
                        market_title=(headerless_recovery or {}).get("market_title", item.get("market") or ""),
                        raw_selection=(headerless_recovery or {}).get("raw_selection", item.get("selection") or ""),
                        odds_str=item.get("odds") or "",
                        raw_text=item.get("raw") or "",
                        section_title=item.get("section_title") or "",
                        home_team=home_team,
                        away_team=away_team,
                        container_id=item.get("container_id") or "",
                        period_hint=item.get("period_hint") or "",
                        ancestor_title=item.get("ancestor_title") or "",
                        main_tab=tab_name,
                        settlement_scope_hint=item.get("settlement_scope_hint") or "",
                        participant_hint=(headerless_recovery or {}).get("participant_hint", item.get("participant_hint")),
                        line_hint=item.get("line_hint") or "",
                        handicap_kind_hint=item.get("handicap_kind") or "",
                        market_instance_id=item.get("market_instance_id") or "",
                        run_id=run_id, event_id=event_id, raw_record_id=raw_record_id,
                        source_raw_record_ids=[raw_record_id],
                    )
                    if odd_rec and (headerless_recovery or {}).get("unrecognized_top_card"):
                        neutralize_unrecognized_top_card(odd_rec)
                    if odd_rec:
                        ledger_entry["terminal_state"] = "PARSED_CANONICAL"
                        odd_rec["capture_id"] = item.get("capture_id") or ""
                        odd_rec["source_index"] = source_idx
                        odd_rec["run_id"] = run_id; odd_rec["event_id"] = event_id
                        odd_rec["raw_record_id"] = raw_record_id; odd_rec["source_raw_record_ids"] = [raw_record_id]
                        odd_rec["MARKET_INSTANCE_ID"] = odd_rec.get("MARKET_INSTANCE_ID") or item.get("market_instance_id") or ""
                        odd_rec["DOM_PATH"] = item.get("dom_path") or item.get("container_id") or ""
                        odd_rec["SECTION_PATH"] = item.get("heading_path") or item.get("section_path") or item.get("ancestor_title") or ""
                        odd_rec["ACTIVE_TAB"] = item.get("active_tab") or tab_name
                        odd_rec["ACTIVE_SUBTAB"] = item.get("active_subtab") or ""
                        # Diagnostic only: text around the market box, used to explain
                        # quarantined rows.  Never part of the bets package.
                        odd_rec["BOX_CONTEXT"] = str(item.get("box_context") or "")[:200]
                        odd_rec["SOURCE_VISIBILITY"] = item.get("visibility") or item.get("source_visibility") or "VISIBLE"
                        odd_rec["RENDER_STATE"] = item.get("render_state") or ""
                        odd_rec["SCROLL_POSITION"] = item.get("scroll_position") or ""
                        attach_structural_provenance(odd_rec, item)
                        extracted_odds.append(odd_rec)
                    if unres_rec:
                        unresolved_items.append(unres_rec)

                tab_name_ascii = unicodedata.normalize("NFKD", tab_name).encode("ascii", "ignore").decode().casefold()
                is_optional_statistics = tab_name_ascii == "statystyki"
                if is_optional_statistics and tab_priced > 0 and not dom_data:
                    event_id = f"{home_team}|{away_team}"
                    evidence_ref = str(html_file.resolve())
                    for optional_index in range(tab_priced):
                        candidate_ledger.append({
                            "run_id": run_id, "event_id": event_id, "source_hash": "", "tab": tab_name,
                            "container_id": "OPTIONAL_STATISTICS", "row_id": str(optional_index), "column_id": "",
                            "native_selection_id": f"optional-statistics:{optional_index}",
                            "evidence_reference": evidence_ref,
                            "terminal_state": "ACCOUNTED_EXCLUDED_WITH_REASON",
                            "reason": "UNSUPPORTED_OPTIONAL_STATISTICS_TAB",
                        })

                tab_summary = candidate_ledger_summary([entry for entry in candidate_ledger if entry.get("tab") == tab_name])
                tab_ledger = tab_summary["by_tab"].get(tab_name, {"parsed":0,"accounted_rejected":0,"foreign_rejected":0,"unaccounted":0})
                tab_parsed_odds = tab_ledger["parsed"]
                tab_unresolved = len(unresolved_items) - tab_unresolved_before
                tab_seconds = round(time.time() - tab_start_time, 1)
                tab_accounted_rejected = tab_ledger["accounted_rejected"]
                tab_unaccounted_priced = tab_ledger["unaccounted"]

                t_status, t_reason = _evaluate_tab_status({
                    "tab_name": tab_name,
                    "activation_ok": True,
                    "interactive_control_count": tab_interactive,
                    "priced_candidate_count": tab_priced,
                    "unpriced_control_count": tab_unpriced,
                    "selectable_count": tab_selectable,
                    "raw_dom_items": tab_raw_dom,
                    "parsed_odds_count": tab_parsed_odds,
                    "unresolved_count": tab_unresolved,
                    "remaining_closed": tab_closed,
                    "remaining_more": tab_more,
                    "deadline_hit": tab_deadline_hit,
                    "exception": tab_exception,
                    "accounted_rejected_count": tab_accounted_rejected,
                    "foreign_rejected_count": tab_ledger["foreign_rejected"],
                    "unaccounted_priced_count": tab_unaccounted_priced,
                })
                # Statistics is optional only when the source exposed priced
                # controls but no usable DOM rows were captured.  A tab that
                # actually parsed rows remains an ordinary, auditable tab; do
                # not silently relabel valid extracted statistics as excluded.
                if _is_optional_statistics_exclusion(tab_name, tab_priced, dom_data, tab_unaccounted_priced):
                    t_status, t_reason = "EXCLUDED_OPTIONAL", "UNSUPPORTED_OPTIONAL_STATISTICS_TAB"

                tab_reports.append({
                    "tab_name": tab_name,
                    "status": t_status,
                    "reason": t_reason,
                    "interactive_control_count": tab_interactive,
                    "priced_candidate_count": tab_priced,
                    "unpriced_control_count": tab_unpriced,
                    "selectable_count": tab_selectable,
                    "raw_dom_items": tab_raw_dom,
                    "parsed_odds_count": tab_parsed_odds,
                    "unresolved_count": tab_unresolved,
                    "remaining_closed": tab_closed,
                    "remaining_more": tab_more,
                    "deadline_hit": tab_deadline_hit,
                    "tab_seconds": tab_seconds,
                    "accounted_rejected_count": tab_accounted_rejected,
                    "foreign_rejected_count": tab_ledger["foreign_rejected"],
                    "unaccounted_priced_count": tab_unaccounted_priced,
                })

            # Ensure no detected tab quietly disappeared
            scanned_names = {tr["tab_name"] for tr in tab_reports}
            for t_name in detected_tab_names:
                if t_name not in scanned_names and t_name not in unscanned_tabs:
                    unscanned_tabs.append(t_name)

            # Save diagnostics
            self.diag.save_raw_html(page.content())
            self.diag.save_screenshot(page)

        except BaseException as exc:
            tb_str = traceback.format_exc()
            self.diag.log(f"UNHANDLED_EXCEPTION: {exc}\n{tb_str}")
            write_history_capture_failed()
            error_code, error_message = _friendly_runtime_error(exc)
            return {"status": "BŁĄD", "error_code": error_code,
                    "error": error_message, "packet_text": "",
                    "odds_count": 0, "market_count": 0, "market_group_count": 0, "unresolved_count": 0}
        finally:
            drain_provider_transport_listener()
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if pw_cm:
                try:
                    pw_cm.__exit__(None, None, None)
                except Exception:
                    pass

        source_hash = _source_hash_from_capture_sources(capture_source_parts)
        _propagate_source_hash(raw_before_dedupe, extracted_odds, source_hash)
        for candidate in candidate_ledger:
            candidate["source_hash"] = source_hash
        for rejection in mycombi_rejection_ledger:
            rejection["source_hash"] = source_hash
        global_candidate_summary = candidate_ledger_summary(candidate_ledger)
        global_unaccounted_priced = global_candidate_summary["unaccounted"]
        ledger_terminal_conflicts = len(global_candidate_summary["conflicts"])
        parsed_candidate_count = sum(tab["parsed"] for tab in global_candidate_summary["by_tab"].values())
        mycombi_state = validate_mycombi_state_for_event(
            {"components": mycombi_components, "combination": mycombi_combination}, home_team, away_team,
            run_id, f"{home_team}|{away_team}", source_hash,
        )
        mycombi_components, mycombi_combination = mycombi_state["components"], mycombi_state["combination"]
        if mycombi_state.get("rejected"):
            raw_before_dedupe = [row for row in raw_before_dedupe if not str(row.get("record_type") or "").startswith("MYCOMBI_")]

        self._notify_stage(0.88, "POST_PROCESSING")
        unique_odds, unresolved_items = _dedupe_records_preserving_order(extracted_odds, unresolved_items)
        source_identity_representative_count = len(unique_odds)

        # POST-PROCESSING 2: exact row-local handicap pairing and one diagnostic per
        # logical instance, regardless of duplicated Top/Wynik representations.
        handicap_audit = analyze_handicap_completeness(unique_odds)
        source_incomplete_instances = {entry["incomplete_instance_id"] for entry in handicap_audit["incomplete_instances"]}
        source_incomplete_rows = [{
            "INCOMPLETE_INSTANCE_ID": entry["incomplete_instance_id"], "MARKET": entry["market"],
            "RAW": " | ".join(str(row.get("RAW") or "") for row in entry["records"]),
            "REASON": "SOURCE_INCOMPLETE_MARKET_INSTANCE", "REPRESENTATION_COUNT": entry["representation_count"],
            "SOURCE_RAW_RECORD_IDS": entry["source_raw_record_ids"], "SOURCE_TABS": entry["source_tabs"],
        } for entry in handicap_audit["incomplete_instances"]]
        excluded_handicap_record_ids = handicap_audit["excluded_record_ids"]
        core_postprocessing_excluded_records = [
            record for record in unique_odds if id(record) in excluded_handicap_record_ids
        ]
        core_postprocessing_excluded_source_ids = {
            str(source_id) for record in core_postprocessing_excluded_records
            for source_id in record.get("source_raw_record_ids") or
            ([record["raw_record_id"]] if record.get("raw_record_id") else [])
        }
        if excluded_handicap_record_ids:
            unique_odds = [record for record in unique_odds if id(record) not in excluded_handicap_record_ids]

        period_resolution = resolve_periods_from_lineage(unique_odds, raw_before_dedupe)
        derived_normalization = derive_market_normalization(unique_odds, home_team, away_team)
        unique_odds, core_semantic_quarantine_rows = partition_semantic_records(unique_odds)
        core_semantic_quarantine = semantic_quarantine_ledger(core_semantic_quarantine_rows)
        player_prop_quarantine = [row for row in core_semantic_quarantine if row["scope"] == "PLAYER_PROP"]
        match_market_quarantine = [row for row in core_semantic_quarantine if row["scope"] == "MATCH_MARKET"]
        optional_statistics_quarantine = [row for row in core_semantic_quarantine if row["scope"] == "OPTIONAL_STATISTICS"]
        # The user-visible key is evaluated after the same owner/column
        # projections used by canonical rows; otherwise equivalent Top/Wynik
        # representations can retain pre-normalization aliases.
        canonical_export_all, export_odds, export_semantic_quarantine_rows, _identical_duplicate_groups, excess_identical_rows = canonical_export_boundary(extracted_odds, home_team, away_team)
        export_semantic_quarantine = semantic_quarantine_ledger(export_semantic_quarantine_rows)
        export_quarantine_counts = semantic_quarantine_scope_counts(export_semantic_quarantine_rows)
        equivalence_groups = build_equivalence_groups(export_odds)

        # COUNTERS
        market_group_count = len(scanned_tabs) if scanned_tabs else 1
        market_count = len({o["CONTAINER_ID"] for o in unique_odds if o.get("CONTAINER_ID")}) or \
                       len({o["MARKET"] for o in unique_odds})
        odds_count = len(export_odds)
        unresolved_count = len(unresolved_items)
        optional_tab_names = {str(report.get("tab_name") or "") for report in tab_reports
                              if report.get("status") == "EXCLUDED_OPTIONAL"}
        optional_statistics_count = sum(
            int(report.get("accounted_rejected_count") or 0) for report in tab_reports
            if report.get("status") == "EXCLUDED_OPTIONAL"
        )
        production_accounting = build_accounting_layers(
            source_raw_records=len(extracted_odds),
            source_identity_representatives=source_identity_representative_count,
            upstream_player_prop_excluded=0,
            upstream_other_excluded=len(core_postprocessing_excluded_source_ids) + optional_statistics_count,
            canonical_export_representatives=len(canonical_export_all), semantic_accepted=len(export_odds),
            semantic_quarantined=len(export_semantic_quarantine_rows), core_usable=len(unique_odds),
            core_semantic_quarantined=len(core_semantic_quarantine_rows),
            core_postprocessing_excluded=len(core_postprocessing_excluded_records), unresolved=unresolved_count,
        )
        core_manifests = [manifest for manifest in coverage_manifests
                          if str(manifest.get("main_tab") or "") not in optional_tab_names]

        # Hard completeness gate: a packet is never analysis-ready if traversal,
        # period binding, raw parity, or unresolved parser truth is incomplete.
        remaining_closed = sum(int(m["remaining_closed"]) for m in core_manifests)
        remaining_more = sum(int(m["remaining_more"]) for m in core_manifests)
        unfinished_scroll = sum(int(m["scroll_containers"]) - int(m["finished_scroll_containers"])
                                for m in core_manifests)
        period_unknown_count = sum(o.get("PERIOD") == "UNKNOWN" for o in unique_odds)
        period_low_confidence_count = sum(o.get("PERIOD_CONFIDENCE") == "LOW" for o in unique_odds)
        parity_ok = all(m["unique_visible_signatures"] == m["raw_exported_signatures"]
                        for m in core_manifests)
        incomplete_reasons: list[str] = []
        if len(scanned_tabs) != len(detected_tabs): incomplete_reasons.append("UNVISITED_MAIN_TAB")
        if any(report.get("status") == "FAIL" for report in tab_reports): incomplete_reasons.append("TAB_STATUS_FAIL")
        if remaining_closed: incomplete_reasons.append("REMAINING_CLOSED")
        if remaining_more: incomplete_reasons.append("REMAINING_MORE")
        if unfinished_scroll: incomplete_reasons.append("UNFINISHED_SCROLL_CONTAINERS")
        if period_unknown_count: incomplete_reasons.append("PERIOD_UNKNOWN")
        if period_low_confidence_count: incomplete_reasons.append("PERIOD_LOW_CONFIDENCE")
        if unresolved_count: incomplete_reasons.append("UNRESOLVED")
        if source_incomplete_instances: incomplete_reasons.append("SOURCE_INCOMPLETE_MARKET_INSTANCE")
        if global_unaccounted_priced:
            incomplete_reasons.append("UNACCOUNTED_PRICED_CANDIDATES")
        if ledger_terminal_conflicts:
            incomplete_reasons.append("LEDGER_TERMINAL_CONFLICT")
        if not parity_ok: incomplete_reasons.append("VISIBLE_RAW_PARITY")
        if any(m["stabilization_passes"] < 3 for m in core_manifests): incomplete_reasons.append("NOT_STABILIZED")
        # A visible market tab without a single row is never silently complete.
        empty_main_tabs = [str(report.get("tab_name") or "") for report in tab_reports
                           if report.get("reason") == "EMPTY_TAB"
                           and str(report.get("tab_name") or "").strip().casefold() != "mycombi"]
        if empty_main_tabs:
            incomplete_reasons.append("EMPTY_MAIN_TAB")
        completeness = completeness_breakdown(
            detected_tabs=len(detected_tabs), scanned_tabs=len(scanned_tabs), raw_records=len(raw_before_dedupe),
            # Canonical dedupe is representation-preserving via lineage: all
            # parsed candidates, not only surviving packet rows, count towards
            # capture completeness.
            parsed_records=parsed_candidate_count, unknown_periods=period_unknown_count,
            incomplete_instances=len(source_incomplete_instances), excluded_rows=sum(
                int(entry.get("REPRESENTATION_COUNT") or 0) for entry in source_incomplete_rows),
            unaccounted_priced=global_unaccounted_priced + ledger_terminal_conflicts,
        )
        completeness_score = completeness["COMPLETENESS_SCORE"]

        self.diag.save_unresolved_log(unresolved_items)
        self.diag.save_dom_json({"coverage_manifest": coverage_manifests,
                                 "tab_reports": tab_reports,
                                 "candidate_ledger": global_candidate_summary,
                                 "mycombi_rejection_ledger": mycombi_rejection_ledger,
                                 "production_accounting": production_accounting,
                                 "core_representative_semantic_quarantine": core_semantic_quarantine,
                                 "player_prop_quarantine": player_prop_quarantine,
                                 "match_market_quarantine": match_market_quarantine,
                                 "optional_statistics_quarantine": optional_statistics_quarantine,
                                 "canonical_export_semantic_quarantine": export_semantic_quarantine,
                                 "incomplete_reasons": incomplete_reasons,
                                 "period_resolution": period_resolution, "derived_normalization": derived_normalization})

        # Zero odds guard
        if odds_count == 0:
            err_msg = "Nie pobrano kursów. Betclic mógł zablokować sesję lub oferta jest niedostępna."
            self.diag.log(f"ZERO_ODDS: {err_msg}")
            return {"status": "BŁĄD", "error_code": "ZERO_ODDS", "error": err_msg,
                    "packet_text": "", "odds_count": 0, "market_count": 0,
                    "market_group_count": 0, "unresolved_count": unresolved_count}

        detected_tab_count = len(detected_tabs)
        scanned_tab_count = len(tab_reports)
        global_truth_status, analysis_ready = _aggregate_parser_truth_status(
            tab_reports, detected_tab_count=detected_tab_count, unscanned_tabs=unscanned_tabs
        )
        if is_live:
            analysis_ready = "NO"
        if incomplete_reasons:
            analysis_ready = "NO"
            if global_truth_status == "PASS":
                global_truth_status = "PARTIAL"

        exhaustive_ready = "NO" if optional_statistics_count or core_semantic_quarantine_rows or incomplete_reasons else "YES"
        full_usable_ready = "YES" if not unresolved_count and not any(reason in incomplete_reasons for reason in (
            "UNVISITED_MAIN_TAB", "REMAINING_CLOSED", "REMAINING_MORE", "UNFINISHED_SCROLL_CONTAINERS",
            "VISIBLE_RAW_PARITY", "NOT_STABILIZED", "UNACCOUNTED_PRICED_CANDIDATES", "TAB_STATUS_FAIL",
            "EMPTY_MAIN_TAB",
        )) else "NO"
        analysis_scope_override = ""
        if full_usable_ready == "YES" and global_truth_status == "PASS":
            analysis_ready = "YES"
            global_truth_status = "PASS"
            analysis_scope_override = ("FULL_USABLE_EXCLUDING_AUDITED_SEMANTIC_QUARANTINE"
                                       if optional_statistics_count or core_semantic_quarantine_rows else
                                       "FULL_USABLE_EXCLUDING_SOURCE_INCOMPLETE")

        # An empty optional tab (named in empty_tabs) leaves the core markets of
        # the other tabs intact: it limits FULL_USABLE, not CLEAN_CORE.
        structural_reasons = [reason for reason in incomplete_reasons if reason not in {
            "PERIOD_UNKNOWN", "PERIOD_LOW_CONFIDENCE", "UNRESOLVED", "EMPTY_MAIN_TAB"
        }]
        clean_core_gate = _evaluate_clean_core_gate(unique_odds, unresolved_items, structural_reasons)
        readiness = _readiness_snapshot(
            analysis_ready, full_usable_ready, exhaustive_ready,
            analysis_scope_override or clean_core_gate["analysis_scope"], global_truth_status,
        )

        capture_time = time.strftime("%Y-%m-%d %H:%M:%S")

        raw_jsonl_path = DIAGNOSTICS_DIR / f"raw_before_dedupe_{run_id}.jsonl"
        raw_written_count, raw_sha256, raw_export_status = _export_raw_jsonl(raw_before_dedupe, raw_jsonl_path)
        if getattr(sys, "frozen", False):
            runtime_core = Path(sys.executable).resolve()
            runtime_artifact = runtime_core
        else:
            runtime_core = Path(__file__).resolve()
            runtime_artifact = runtime_core.with_name("gui.py")
        # Runtime metadata identifies the supported product entrypoint, not the
        # incidental caller (unit test, diagnostic script, or ``python -c``).
        runtime_entrypoint = str(runtime_artifact)
        runtime_artifact_sha256 = hashlib.sha256(runtime_artifact.read_bytes()).hexdigest()
        runtime_core_sha256 = hashlib.sha256(runtime_core.read_bytes()).hexdigest()
        runtime_build_time = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(runtime_core.stat().st_mtime))

        packet_lines = [
            "BETCLIC_FULL_ODDS_PACKET{",
            f'BUILD_ID="{BUILD_ID}";',
            f'RUNTIME_ENTRYPOINT="{runtime_entrypoint}";',
            f'RUNTIME_ARTIFACT_PATH="{runtime_artifact}";',
            f'RUNTIME_ARTIFACT_SHA256="{runtime_artifact_sha256}";',
            f'CORE_PATH="{runtime_core}";',
            f'CORE_SHA256="{runtime_core_sha256}";',
            f'RUNTIME_BUILD_TIME="{runtime_build_time}";',
            f'SOURCE_URL="{url}";',
            f'MATCH="{match_str}";',
            f'COMPETITION="{comp_str}";',
            f'KICKOFF="{kickoff_str}";',
            f'KICKOFF_SOURCE="{kickoff_source}";',
            f'EVENT_STATUS="{event_status}";',
            f'PARSER_TRUTH_STATUS="{readiness["PARSER_TRUTH_STATUS"]}";',
            f'ANALYSIS_READY="{readiness["ANALYSIS_READY"]}";',
            f'CLEAN_CORE_READY="{clean_core_gate["clean_core_ready"]}";',
            f'ANALYSIS_SCOPE="{readiness["ANALYSIS_SCOPE"]}";',
            f'EXHAUSTIVE_READY="{readiness["EXHAUSTIVE_READY"]}";',
            f'FULL_USABLE_READY="{readiness["FULL_USABLE_READY"]}";',
            f"SOURCE_INCOMPLETE_INSTANCE_COUNT={len(source_incomplete_instances)};",
            f"EXCLUDED_ROWS={len(source_incomplete_rows)};",
            f'OPTIONAL_TABS_EXCLUDED="{"Statystyki" if optional_statistics_count else ""}";',
            f"OPTIONAL_ODDS_EXCLUDED_COUNT={optional_statistics_count};",
            f'ACCOUNTING_SCHEMA_VERSION="{production_accounting["ACCOUNTING_SCHEMA_VERSION"]}";',
            f'SEMANTIC_QUARANTINE_SCHEMA_VERSION="{production_accounting["SEMANTIC_QUARANTINE_SCHEMA_VERSION"]}";',
            f"SOURCE_RAW_RECORDS={production_accounting['SOURCE_RAW_RECORDS']};",
            f"SOURCE_IDENTITY_REPRESENTATIVE_COUNT={production_accounting['SOURCE_IDENTITY_REPRESENTATIVE_COUNT']};",
            f"SOURCE_DUPLICATE_ROWS_SUPPRESSED={production_accounting['SOURCE_DUPLICATE_ROWS_SUPPRESSED']};",
            f"UPSTREAM_PLAYER_PROP_EXCLUDED_COUNT={production_accounting['UPSTREAM_PLAYER_PROP_EXCLUDED_COUNT']};",
            f"UPSTREAM_OTHER_EXCLUDED_COUNT={production_accounting['UPSTREAM_OTHER_EXCLUDED_COUNT']};",
            f"CANONICAL_EXPORT_REPRESENTATIVE_COUNT={production_accounting['CANONICAL_EXPORT_REPRESENTATIVE_COUNT']};",
            f"SEMANTIC_ACCEPTED_COUNT={production_accounting['SEMANTIC_ACCEPTED_COUNT']};",
            f"CORE_USABLE_REPRESENTATIVE_COUNT={production_accounting['CORE_USABLE_REPRESENTATIVE_COUNT']};",
            f"CORE_REPRESENTATIVE_SEMANTIC_QUARANTINED_COUNT={production_accounting['CORE_REPRESENTATIVE_SEMANTIC_QUARANTINED_COUNT']};",
            f"CORE_POSTPROCESSING_EXCLUDED_REPRESENTATIVE_COUNT={production_accounting['CORE_POSTPROCESSING_EXCLUDED_REPRESENTATIVE_COUNT']};",
            f"CANONICAL_EXPORT_SEMANTIC_QUARANTINED_COUNT={production_accounting['SEMANTIC_QUARANTINED_COUNT']};",
            f"PLAYER_PROP_QUARANTINED_COUNT={export_quarantine_counts['PLAYER_PROP']};",
            f"MATCH_MARKET_QUARANTINED_COUNT={export_quarantine_counts['MATCH_MARKET']};",
            f"OPTIONAL_STATISTICS_QUARANTINED_COUNT={export_quarantine_counts['OPTIONAL_STATISTICS']};",
        ]
        if is_live:
            packet_lines.append('BLOCK_REASON="LIVE_EVENT";')
        packet_lines.extend([
            f'VISIBLE_TABS="{",".join(t[0] for t in (detected_tabs if detected_tabs else [("GŁÓWNE",None)]))}";',
            f'TABS_SCANNED="{",".join(scanned_tabs)}";',
            f"DETECTED_TAB_COUNT={detected_tab_count};",
            f"SCANNED_TAB_COUNT={scanned_tab_count};",
            f'UNSCANNED_TABS="{",".join(unscanned_tabs)}";',
            f"MARKET_GROUP_COUNT={market_group_count};",
            f"MARKET_COUNT={market_count};",
            f"ODDS_COUNT={odds_count};",
            f"RAW_ODDS_COUNT={len(extracted_odds)};",
            f"CANONICAL_ODDS_COUNT={len(canonical_export_all)};",
            f"CANONICAL_DUPLICATES_SUPPRESSED={excess_identical_rows};",
            "IDENTICAL_DUPLICATE_GROUPS=0;",
            "EXCESS_IDENTICAL_ROWS=0;",
            f"EQUIVALENCE_GROUPS={len(equivalence_groups)};",
            f"UNRESOLVED_COUNT={unresolved_count};",
            f"COMPLETENESS_SCORE={completeness_score};",
            f"COMPLETENESS_TAB_COVERAGE={completeness['COMPLETENESS_TAB_COVERAGE']};",
            f"COMPLETENESS_PARSE={completeness['COMPLETENESS_PARSE']};",
            f"COMPLETENESS_PERIOD={completeness['COMPLETENESS_PERIOD']};",
            f"COMPLETENESS_MARKET_INSTANCES={completeness['COMPLETENESS_MARKET_INSTANCES']};",
            f"COMPLETENESS_EXCLUSION={completeness['COMPLETENESS_EXCLUSION']};",
            f"UNIQUE_INCOMPLETE_INSTANCE_COUNT={completeness['UNIQUE_INCOMPLETE_INSTANCE_COUNT']};",
            f"DUPLICATE_INCOMPLETE_ROWS_SUPPRESSED={completeness['DUPLICATE_INCOMPLETE_ROWS_SUPPRESSED']};",
            f'INCOMPLETE_REASONS="{",".join(incomplete_reasons)}";',
            f"REMAINING_CLOSED={remaining_closed};",
            f"REMAINING_MORE={remaining_more};",
            f"UNFINISHED_SCROLL_CONTAINERS={unfinished_scroll};",
            *(f'{key}="{value}";' for key, value in period_accounting(export_odds, core_semantic_quarantine_rows, canonical_export_all, unique_odds).items()),
            'SEMANTIC_QUARANTINE_EMISSION_SCOPE="CORE_REPRESENTATIVES";',
            f"EMITTED_SEMANTIC_QUARANTINE_COUNT={len(core_semantic_quarantine_rows)};",
            f"EMITTED_PLAYER_PROP_QUARANTINE_COUNT={len(player_prop_quarantine)};",
            f"EMITTED_OPTIONAL_STATISTICS_QUARANTINE_COUNT={len(optional_statistics_quarantine)};",
            f"EXCLUDED_UNKNOWN_COUNT={clean_core_gate["excluded_unknown_count"]};",
            f"EXCLUDED_UNRESOLVED_COUNT={clean_core_gate["excluded_unresolved_count"]};",
            f'CAPTURE_TIME="{capture_time}";',
            "}",
            "",
            "[TAB_TRUTH]",
        ])

        for tr in tab_reports:
            deadline_str = "YES" if tr["deadline_hit"] else "NO"
            sec_val = tr.get("tab_seconds", 0.0)
            packet_lines.append(
            f'TAB={tr["tab_name"]}|STATUS={tr["status"]}|INTERACTIVE={tr.get("interactive_control_count", 0)}|'
            f'PRICED={tr.get("priced_candidate_count", 0)}|UNPRICED={tr.get("unpriced_control_count", 0)}|'
            f'RAW={tr["raw_dom_items"]}|PARSED={tr["parsed_odds_count"]}|UNRESOLVED={tr["unresolved_count"]}|'
            f'ACCOUNTED_REJECTED={tr.get("accounted_rejected_count", 0)}|UNACCOUNTED_PRICED={tr.get("unaccounted_priced_count", 0)}|'
                f'CLOSED={tr["remaining_closed"]}|MORE={tr["remaining_more"]}|DEADLINE={deadline_str}|'
                f'SECONDS={sec_val:.1f}|REASON={tr["reason"]}'
            )

        packet_lines.extend([
            "",
            "[ARTIFACTS]",
            f'RUN_ID="{run_id}";',
            f'RAW_FILE="{raw_jsonl_path.resolve()}";',
            f"RAW_MEMORY_COUNT={len(raw_before_dedupe)};",
            f"RAW_WRITTEN_COUNT={raw_written_count};",
            f'RAW_SHA256="{raw_sha256}";',
            f'RAW_EXPORT_STATUS="{raw_export_status}";',
            f"TAB_HTML_COUNT={tab_html_count};",
            f"TAB_SCREENSHOT_COUNT={tab_screenshot_count};",
            f"EVIDENCE_ERRORS={evidence_errors};",
            "",
        ])

        for item in export_odds:
            packet_lines += [
                "ODD{",
                f'CATEGORY="{item["CATEGORY"]}";',
                f'FAMILY="{item["FAMILY"]}";',
                f'MARKET="{item["MARKET"]}";',
                f'PERIOD="{item["PERIOD"]}";',
                f'OWNER="{item["OWNER"]}";',
                f'SELECTION="{item["SELECTION"]}";',
                f'LINE="{item["LINE"]}";',
                f'HANDICAP_KIND="{item.get("HANDICAP_KIND", "")}";',
                f'HANDICAP_TAXONOMY="{item.get("HANDICAP_TAXONOMY", "")}";',
                f'SETTLEMENT="{item.get("SETTLEMENT", "")}";',
                f'ODDS="{item["ODDS"]}";',
                f'RAW="{item["RAW"]}";',
                f'PERIOD_SOURCE="{item.get("PERIOD_SOURCE", "")}";',
                f'PERIOD_CONFIDENCE="{item.get("PERIOD_CONFIDENCE", "")}";',
                f'SCORER_SCOPE="{item.get("SCORER_SCOPE", "")}";',
                f'PARTICIPANT="{item.get("PARTICIPANT", "")}";',
                f'SOURCE_RAW_RECORD_IDS="{",".join(item.get("source_raw_record_ids") or [])}";',
                f'MARKET_INSTANCE_ID="{item.get("MARKET_INSTANCE_ID", "")}";',
                "}",
                "",
            ]

        for group in equivalence_groups:
            packet_lines += [
                "EQUIVALENCE_GROUP{",
                f'SIGNATURE="{group["signature"]}";',
                f'BEST_ODDS="{group["best_odds"]}";',
                f'BEST_MARKET="{group["best_market"]}";',
                f'BEST_CATEGORY="{group["best_category"]}";',
                "COPIES=" + json.dumps(group["copies"], ensure_ascii=False, separators=(",", ":")) + ";",
                "}",
                "",
            ]

        for component in mycombi_components:
            packet_lines += [
                "MYCOMBI_COMPONENT{",
                f'COMPONENT_ID="{component["component_id"]}";',
                f'LABEL="{component["label"]}";',
                f'MARKET_HEADING="{component["market_heading"]}";',
                f'OWNER="{component["owner"]}";',
                f'PERIOD="{component["period"]}";',
                f'PERIOD_SOURCE="{component["period_source"]}";',
                f'PERIOD_CONFIDENCE="{component["period_confidence"]}";',
                f'LINE="{component["line"] if component["line"] is not None else ""}";',
                f'SETTLEMENT="{component["settlement"]}";',
                f'DISPLAY_ORDER={component["display_order"]};',
                "SELECTED=YES;",
                "INDIVIDUAL_ODDS=null;",
                'SOURCE="BETCLIC_MYCOMBI_COMPONENT";',
                "}",
                "",
            ]

        if mycombi_combination:
            packet_lines += [
                "MYCOMBI_COMBINATION{",
                f'COMBINATION_ID="{mycombi_combination["combination_id"]}";',
                f'COMPONENT_IDS="{",".join(mycombi_combination["components"])}";',
                f'COMPONENT_COUNT={mycombi_combination["component_count"]};',
                f'COMBINED_ODDS="{mycombi_combination["combined_odds"]}";',
                f'UI_REPRESENTATION_COUNT={mycombi_combination["ui_representation_count"]};',
                f'STATUS="{mycombi_combination["status"]}";',
                'SOURCE="BETCLIC_MYCOMBI_GENERATED_PRICE";',
                "}",
                "",
            ]

        for unres in unresolved_items:
            packet_lines += [
                "UNRESOLVED{",
                f'MARKET="{unres.get("MARKET", "")}";',
                f'RAW="{unres.get("RAW", "")}";',
                f'REASON="{unres.get("REASON", "")}";',
                "}",
                "",
            ]

        for source_item in source_incomplete_rows:
            packet_lines += [
                "SOURCE_INCOMPLETE{",
                f'MARKET="{source_item.get("MARKET", "")}";',
                f'RAW="{source_item.get("RAW", "")}";',
                'REASON="SOURCE_INCOMPLETE_MARKET_INSTANCE";',
                "}",
                "",
            ]

        for quarantined in core_semantic_quarantine:
            packet_lines += [
                "SEMANTIC_QUARANTINE{",
                f'SCOPE="{quarantined.get("scope", "")}";',
                f'FAMILY="{quarantined.get("family", "")}";',
                f'TAB="{quarantined.get("tab", "")}";',
                f'MARKET="{quarantined["market"]}";',
                f'SELECTION="{quarantined["selection"]}";',
                f'OWNER="{quarantined["owner"]}";',
                f'PERIOD="{quarantined["period"]}";',
                f'SETTLEMENT="{quarantined.get("settlement", "")}";',
                *(f'{key.upper()}="{quarantined.get(key, "")}";' for key in
                  ("declared_winning_event", "winning_event_source", "payout_contract", "contract_missing")),
                f'ODDS="{quarantined.get("odds", "")}";',
                f'RAW_ORIGINAL="{quarantined.get("raw_original", "")}";',
                f'REASON="{quarantined.get("reason", "")}";',
                f'SOURCE_RAW_RECORD_IDS="{",".join(quarantined["source_raw_record_ids"])}";',
                'BOX_CONTEXT="' + str(quarantined.get("box_context", "")).replace('"', "'").replace("\\", "/").replace("\n", " ") + '";',
                "}",
                "",
            ]

        packet_text = "\n".join(packet_lines)
        # packet_text is the internal machine packet: the Context Engine needs
        # its lineage ids and accounting, diagnostics keep the rest.  Users and
        # LLMs get only the bets, natively serialized without any of that.
        # The embedded kickoff instant belongs to this event only when the page's
        # match id equals the URL's event id (same rule as the history contract).
        kickoff_utc = (canonicalize_utc_datetime(embedded_provider_info.get("match_date_utc"))
                       if route_event_id and embedded_provider_info.get("provider_match_id") == route_event_id
                       else None) or ""
        llm_packet_text = llm_packet(match_str, comp_str, kickoff_str, export_odds, readiness, empty_main_tabs,
                                     kickoff_utc, capture_started_at or "")
        elapsed = round(time.time() - run_start_time, 2)
        self.diag.log(f"Extraction done in {elapsed}s: truth_status={global_truth_status}, ready={analysis_ready}, tabs={scanned_tabs}, markets={market_count}, odds={odds_count}, unresolved={unresolved_count}")

        # Write runtime build info JSON
        try:
            build_info = {
                "BUILD_ID": BUILD_ID,
                "RUNTIME_ENTRYPOINT": runtime_entrypoint,
                "RUNTIME_ARTIFACT_PATH": str(runtime_artifact),
                "RUNTIME_ARTIFACT_SHA256": runtime_artifact_sha256,
                "CORE_PATH": str(runtime_core),
                "CORE_SHA256": runtime_core_sha256,
                "RUNTIME_BUILD_TIME": runtime_build_time,
                "CAPTURE_TIME": capture_time,
                "SOURCE_URL": url,
                "MATCH": match_str,
                **readiness,
                "CLEAN_CORE_READY": clean_core_gate["clean_core_ready"],
                "SCANNED_TABS": scanned_tabs,
                "MARKET_GROUP_COUNT": market_group_count,
                "MARKET_COUNT": market_count,
                "ODDS_COUNT": odds_count,
                "UNRESOLVED_COUNT": unresolved_count,
                "COMPLETENESS_SCORE": completeness_score,
                "INCOMPLETE_REASONS": incomplete_reasons,
                "PERIOD_RESOLUTION": period_resolution,
                "DERIVED_NORMALIZATION": derived_normalization,
                "COVERAGE_MANIFEST": coverage_manifests,
            }
            info_path = LOGS_DIR.parent / "runtime_build_info.json"
            info_path.write_text(json.dumps(build_info, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        capture_finished_at = utc_now_rfc3339()
        history_status = evaluate_capture_status(
            route_event_id, embedded_provider_info, preflight_status,
            capture_started_at, capture_finished_at,
        )
        history_observations = [
            build_history_observation(
                raw_observation, history_status["provider_event_id"], history_status["kickoff_at"],
                observed_at, observation_sequence,
            )
            for raw_observation, observed_at, observation_sequence in history_observation_seeds
        ]
        try:
            history_sidecars = write_history_sidecars(HISTORY_V0_1_DIR, {
                "schema_version": "APEX_HISTORY_COLLECTION_CONTRACT_V0_1",
                "run_id": run_id, "provider": "BETCLIC",
                "provider_event_id": history_status["provider_event_id"], "source_url": url,
                "kickoff_at": history_status["kickoff_at"], "kickoff_timezone": "UTC",
                "kickoff_source": "BETCLIC_EMBEDDED_MATCH_DATE_UTC",
                "capture_started_at": capture_started_at, "capture_finished_at": capture_finished_at,
                "capture_clock_timezone": "UTC", "provider_is_live": history_status["provider_is_live"],
                "preflight_status": preflight_status, "capture_status": history_status["capture_status"],
                "collector_version": BUILD_ID,
                "identity_validation": {"route_event_id": route_event_id,
                                        "embedded_match_id": history_status["embedded_match_id"],
                                        "exact_match": history_status["exact_match"]},
            }, history_observations)
            if history_status["capture_status"] == "PREMATCH_VALID":
                # The mapping is capture-time evidence only.  It is stored
                # separately from the immutable prematch snapshot so later
                # outcome labels cannot alter quote state or snapshot hashes.
                try:
                    bridge = build_provider_derived_bridge(
                        history_status["provider_event_id"], captured_page_html,
                        f"history_v0_1/hydration/run_{run_id}",
                        capture_started_at,
                    )
                    bridge_path = write_bridge_append_only(HISTORY_IDENTITY_BRIDGE_V0_1_DIR, bridge)
                    self.diag.log(f"HISTORY_IDENTITY_BRIDGE_V0_1={bridge_path}")
                    if transport_listener is not None:
                        log_provider_transport_listener_errors(self.diag, transport_listener)
                        records = transport_listener.flush(HISTORY_PROVIDER_TRANSPORT_V0_1_DIR, bridge)
                        self.diag.log(f"HISTORY_PROVIDER_TRANSPORT_V0_1_COUNT={len(records)}")
                        log_provider_transport_flush_summary(self.diag, transport_listener)
                except IdentityBridgeValidationError:
                    self.diag.log("HISTORY_IDENTITY_BRIDGE_V0_1_UNAVAILABLE")
                manifest_path = build_and_write_manifest(
                    Path(history_sidecars["run_sidecar_path"]),
                    Path(history_sidecars["observations_sidecar_path"]),
                    HISTORY_SNAPSHOT_MANIFEST_V0_1_DIR,
                )
                self.diag.log(f"HISTORY_SNAPSHOT_MANIFEST_V0_1={manifest_path}")
        except Exception as history_exc:
            self.diag.log(f"HISTORY_V0_1_SIDECAR_OR_MANIFEST_WRITE_FAILED: {type(history_exc).__name__}")

        self._notify_stage(1.0, "FINISHED")

        return {
            "status": "GOTOWE" if global_truth_status == "PASS" else ("PARTIAL" if global_truth_status == "PARTIAL" else "BŁĄD"),
            "parser_truth_status": readiness["PARSER_TRUTH_STATUS"],
            "analysis_ready": readiness["ANALYSIS_READY"],
            "clean_core_ready": clean_core_gate["clean_core_ready"],
            "analysis_scope": readiness["ANALYSIS_SCOPE"],
            "exhaustive_ready": readiness["EXHAUSTIVE_READY"],
            "full_usable_ready": readiness["FULL_USABLE_READY"],
            "period_resolution": period_resolution,
            "derived_normalization": derived_normalization,
            "source_incomplete_instances": sorted(source_incomplete_instances),
            "source_incomplete_rows": source_incomplete_rows,
            "excluded_rows": len(source_incomplete_rows),
            "excluded_unknown_count": clean_core_gate["excluded_unknown_count"],
            "excluded_unresolved_count": clean_core_gate["excluded_unresolved_count"],
            "tab_reports": tab_reports,
            "candidate_ledger": global_candidate_summary,
            "mycombi_rejection_ledger": mycombi_rejection_ledger,
            "build_id": BUILD_ID,
            "source_url": url,
            "match": match_str,
            "competition": comp_str,
            "kickoff": kickoff_str, "kickoff_source": kickoff_source,
            "market_group_count": market_group_count,
            "market_count": market_count,
            "odds_count": odds_count,
            "unresolved_count": unresolved_count,
            "completeness": completeness,
            "coverage_manifest": coverage_manifests,
            "incomplete_reasons": incomplete_reasons,
            "empty_tabs": empty_main_tabs,
            "scanned_tabs": scanned_tabs,
            "odds": unique_odds,
            "unresolved": unresolved_items,
            "equivalence_groups": equivalence_groups,
            "packet_text": packet_text,
            "llm_packet_text": llm_packet_text,
            "execution_time_sec": elapsed,
        }
