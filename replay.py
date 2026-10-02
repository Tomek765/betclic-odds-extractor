"""Deterministic parser replay for saved, immutable Betclic captures."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from core import (
    attach_structural_provenance,
    canonical_export_boundary,
    _dedupe_canonical_export_rows,
    _dedupe_records_preserving_order,
    analyze_handicap_completeness,
    build_accounting_layers,
    classify_period_evidence,
    completeness_breakdown,
    derive_market_normalization,
    extract_current_event_kickoff,
    partition_semantic_records,
    resolve_periods_from_lineage,
    semantic_quarantine_ledger,
    semantic_quarantine_scope_counts,
    validate_mycombi_state_for_event,
)
from parser import (headerless_top_card_exclusion, neutralize_unrecognized_top_card,
                    parse_market_record, recover_headerless_top_offer)

REAL_RUN_JSONL = Path("diagnostics/raw_before_dedupe_run_1785259772_7560.jsonl")
LEGACY_GROUPED_PERIOD_SNAPSHOT_RUNS = frozenset({"1785269255_18296"})
FULL_USABLE_SOURCE_INCOMPLETE_RUNS = frozenset({"1785272483_10292"})


def semantic_quality_report(*, parsed_records: int, accepted_records: int,
                            quarantined_rows: list[dict[str, Any]],
                            completeness: dict[str, Any], full_usable_ready: str,
                            exhaustive_ready: str) -> dict[str, Any]:
    """Report capture, core, semantic, and exhaustive truth independently.

    Quarantine is retained as evidence and never changes the existing readiness
    gates.  Materiality is based on canonical family, not a count of exclusions.
    """
    core_families = {"1X2", "DNB", "DOUBLE_CHANCE", "HANDICAP_EUROPEAN",
                     "GOALS_OU", "BTTS", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"}
    impacts = {"NONE": 0, "LOW": 1, "MATERIAL": 2, "BLOCKING": 3}
    inverse_impacts = {value: key for key, value in impacts.items()}
    severity = 0
    for row in quarantined_rows:
        if row.get("FAMILY") in core_families:
            severity = max(severity, impacts["MATERIAL"])
        elif row.get("FAMILY") in {"PLAYER_PROP", "GOALSCORER", "UNSUPPORTED_COMPOUND", "UNSUPPORTED_SPECIALTY"}:
            severity = max(severity, impacts["NONE"])
        else:
            severity = max(severity, impacts["LOW"])
    ratio = 100.0 if parsed_records <= 0 else round(100.0 * accepted_records / parsed_records, 1)
    return {
        "CAPTURE_COVERAGE": completeness["COMPLETENESS_PARSE"],
        "CORE_MARKET_USABILITY": "PASS" if full_usable_ready == "YES" else "FAIL",
        "SEMANTIC_ACCEPTANCE_RATIO": ratio,
        "EXHAUSTIVE_SUPPORT_STATUS": "FULL" if exhaustive_ready == "YES" else "PARTIAL",
        "CORE_IMPACT": inverse_impacts[severity],
        "QUARANTINE_COUNT": len(quarantined_rows),
    }


def _matching_historical_diagnostic(path: Path, source_ids: set[str]) -> Path | None:
    """Find the production DOM diagnostic whose ledger belongs to this raw file."""
    run_match = re.fullmatch(r"raw_before_dedupe_run_(\d+)_\d+\.jsonl", path.name)
    if run_match:
        timestamp_named = path.parent / f"dom_{run_match.group(1)}.json"
        if timestamp_named.is_file():
            return timestamp_named
    if not source_ids:
        return None
    for diagnostic in sorted(path.parent.glob("dom_*.json")):
        try:
            payload = json.loads(diagnostic.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ledger = (payload.get("core_representative_semantic_quarantine") or
                  payload.get("semantic_quarantine") or
                  payload.get("player_prop_quarantine") or [])
        ledger_ids = {source_id for row in ledger for source_id in row.get("source_raw_record_ids") or []}
        if ledger_ids and ledger_ids <= source_ids:
            return diagnostic
    return None


def _historical_legacy_quarantine_evidence(diagnostic: Path | None) -> tuple[int | None, str]:
    """Read immutable legacy evidence without treating its field name as truth."""
    if diagnostic is None:
        return None, "NO_MATCHING_HISTORICAL_DIAGNOSTIC"
    try:
        payload = json.loads(diagnostic.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "HISTORICAL_DIAGNOSTIC_UNREADABLE"
    if payload.get("semantic_quarantine_schema_version"):
        ledger = payload.get("core_representative_semantic_quarantine") or []
        return len(ledger), "CURRENT_SEMANTIC_QUARANTINE_SCHEMA"
    # The old field held all semantic exclusions, including unsupported match
    # markets.  Its contents remain evidence, but the old name is never a new
    # player-prop metric.
    return len(payload.get("player_prop_quarantine") or []), "LEGACY_MISNAMED_PLAYER_PROP_QUARANTINE"


def _historical_packet_odds_count(diagnostic: Path | None) -> int | None:
    """Read the immutable production summary paired with a DOM diagnostic."""
    if diagnostic is None:
        return None
    run_stamp = diagnostic.stem.removeprefix("dom_")
    log_path = diagnostic.parent.parent / "logs" / f"extractor_{run_stamp}.log"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    matches = re.findall(r"Extraction done .*? odds=(\d+), unresolved=\d+", text)
    return int(matches[-1]) if matches else None


def production_accounting_report(*, raw_rows: list[dict[str, Any]], parsed_records: list[dict[str, Any]],
                                 source_identity_representative_count: int, home_team: str, away_team: str,
                                 path: Path, core_usable_representative_count: int,
                                 core_semantic_quarantined_count: int,
                                 core_postprocessing_excluded_count: int,
                                 upstream_other_excluded_count: int, unresolved_count: int) -> dict[str, Any]:
    """Replay the production export boundary without altering replay semantics.

    Production builds packet odds from ``extracted_odds`` through the separate
    canonical-export dedupe helper.  ``odds`` in this module deliberately keeps
    its older representative-layer contract; this report exposes the production
    layer next to it, with source-ID accounting for both terminal outcomes.
    """
    canonical_rows, accepted_rows, quarantined_rows, duplicate_groups, suppressed_rows = canonical_export_boundary(parsed_records, home_team, away_team)
    quarantine_counts = semantic_quarantine_scope_counts(quarantined_rows)

    def ids(rows: list[dict[str, Any]]) -> set[str]:
        return {
            str(source_id) for row in rows
            for source_id in row.get("source_raw_record_ids") or
            ([row["raw_record_id"]] if row.get("raw_record_id") else [])
        }

    raw_ids = ids(raw_rows)
    accepted_ids, quarantined_ids = ids(accepted_rows), ids(quarantined_rows)
    terminal_ids = accepted_ids | quarantined_ids
    historical_diagnostic = _matching_historical_diagnostic(path, raw_ids)
    historical_quarantine_count, historical_quarantine_status = _historical_legacy_quarantine_evidence(historical_diagnostic)
    historical_packet_odds_count = _historical_packet_odds_count(historical_diagnostic)
    unaccounted_source_ids = raw_ids - terminal_ids
    report = build_accounting_layers(
        source_raw_records=len(raw_rows), source_identity_representatives=source_identity_representative_count,
        upstream_player_prop_excluded=0, upstream_other_excluded=upstream_other_excluded_count,
        canonical_export_representatives=len(canonical_rows), semantic_accepted=len(accepted_rows),
        semantic_quarantined=len(quarantined_rows), core_usable=core_usable_representative_count,
        core_semantic_quarantined=core_semantic_quarantined_count,
        core_postprocessing_excluded=core_postprocessing_excluded_count, unresolved=unresolved_count,
    )
    report.update({
        "RAW_SOURCE_COUNT": len(raw_rows),
        "POST_RAW_DEDUPE_COUNT": source_identity_representative_count,
        "CANONICAL_ODDS_COUNT": len(canonical_rows),
        "CANONICAL_DUPLICATE_GROUPS": duplicate_groups,
        "CANONICAL_DUPLICATES_SUPPRESSED": suppressed_rows,
        "CURRENT_PLAYER_PROP_QUARANTINED_COUNT": quarantine_counts["PLAYER_PROP"],
        "CURRENT_MATCH_MARKET_QUARANTINED_COUNT": quarantine_counts["MATCH_MARKET"],
        "CURRENT_OPTIONAL_STATISTICS_QUARANTINED_COUNT": quarantine_counts["OPTIONAL_STATISTICS"],
        "SOURCE_ACCEPTED_COUNT": len(accepted_ids),
        "SOURCE_QUARANTINED_COUNT": len(quarantined_ids),
        "SOURCE_TERMINAL_COUNT": len(terminal_ids),
        "UNACCOUNTED_SOURCE_RECORD_COUNT": len(unaccounted_source_ids),
        "ALL_SOURCE_IDS_PRESERVED": not unaccounted_source_ids and not (accepted_ids & quarantined_ids),
        "LEGACY_REPORTED_SEMANTIC_QUARANTINE_COUNT": historical_quarantine_count,
        "LEGACY_REPORTED_SEMANTIC_QUARANTINE_STATUS": historical_quarantine_status,
        "LEGACY_REPORTED_PACKET_ODDS_COUNT": historical_packet_odds_count,
    })
    return report


def load_real_prematch_fixture(path: Path = REAL_RUN_JSONL) -> list[dict[str, Any]]:
    """Load the saved run only; this function never opens a browser or network."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    # Enrichment is explicit metadata from this capture's snapshot; RAW and the
    # saved JSONL remain unchanged. Never infer a foreign event's short names.
    from team_name_evidence import saved_native_team_names
    home, away = _capture_teams(rows)
    evidence = saved_native_team_names(path, home, away) if home and away else {}
    if evidence:
        for row in rows:
            row.setdefault("native_team_names", evidence)
    return rows


def _capture_teams(rows: list[dict[str, Any]]) -> tuple[str, str]:
    """Read explicit event identity before using legacy market-title fallbacks."""
    event_ids = {str(row.get("event_id") or "") for row in rows if "|" in str(row.get("event_id") or "")}
    if len(event_ids) == 1:
        home, away = next(iter(event_ids)).split("|", 1)
        if home and away:
            return home, away
    # Legacy captures without event_id: read team names from team-total titles.
    teams: list[str] = []
    for row in rows:
        market = str(row.get("market") or "")
        if not market.lower().startswith("liczba goli - "):
            continue
        team = market.split(" - ", 1)[1].strip()
        if team and not any(char.isdigit() for char in team) and team not in teams:
            teams.append(team)
    return (teams[0], teams[1]) if len(teams) >= 2 else ("", "")


def _capture_container_identity(row: dict[str, Any]) -> str:
    """Use persisted structural provenance when the legacy container_id is empty."""
    if row.get("container_id"):
        return str(row["container_id"])
    market_instance_id = str(row.get("market_instance_id") or "")
    if "|row#" in market_instance_id:
        return market_instance_id.split("|row#", 1)[0]
    return "|".join((str(row.get("active_tab") or row.get("tab_name") or ""),
                      str(row.get("heading_path") or row.get("market") or "")))


def _is_mycombi_betslip_ui_row(row: dict[str, Any]) -> bool:
    """Readonly bet-slip price copies are UI evidence, not ordinary odds rows."""
    tab = str(row.get("active_tab") or row.get("tab_name") or "").strip().casefold()
    dom_path = str(row.get("dom_path") or "").casefold()
    return tab == "mycombi" and "sports-betting-slip" in dom_path and str(row.get("record_type") or "ODD") == "ODD"


def _saved_capture_kickoff(path: Path) -> tuple[str, str]:
    match = re.fullmatch(r"raw_before_dedupe_run_(\d+)_\d+\.jsonl", path.name)
    if not match:
        return "", "KICKOFF_SOURCE_MISSING"
    snapshot = path.parent.parent / "snapshots" / f"snapshot_{match.group(1)}.html"
    if not snapshot.exists():
        return "", "KICKOFF_SOURCE_MISSING"
    html = snapshot.read_text(encoding="utf-8", errors="replace")
    hour = re.search(r'class="[^"]*scoreboard_hour[^"]*"[^>]*>\s*([^<]+?)\s*<', html, re.IGNORECASE)
    return extract_current_event_kickoff("", hour.group(1) if hour else "")


def audit_same_run_lineage(
    evidence_source_ids: set[str], canonical_records: list[dict[str, Any]],
    excluded_lineage: list[dict[str, Any]], *, run_id: str, event_id: str, source_hash: str,
) -> dict[str, int]:
    """Account evidence IDs in one terminal state without changing market semantics."""
    canonical_ids = {
        source_id for record in canonical_records
        for source_id in (record.get("source_raw_record_ids") or
                          ([record["raw_record_id"]] if record.get("raw_record_id") else []))
    }
    excluded_ids: list[str] = []
    excluded_foreign_run = excluded_foreign_event = excluded_foreign_hash = 0
    for entry in excluded_lineage:
        ids = entry.get("source_raw_record_ids") or ([entry["raw_record_id"]] if entry.get("raw_record_id") else [])
        excluded_ids.extend(ids)
        excluded_foreign_run += int(entry.get("run_id", "") != run_id)
        excluded_foreign_event += int(entry.get("event_id", "") != event_id)
        excluded_foreign_hash += int(entry.get("source_hash", "") != source_hash)
    excluded_set = set(excluded_ids)
    conflicting = canonical_ids & excluded_set
    duplicate_excluded = {source_id for source_id in excluded_set if excluded_ids.count(source_id) > 1}
    multi_conflict = conflicting | duplicate_excluded
    accounted_canonical = evidence_source_ids & canonical_ids
    accounted_excluded = evidence_source_ids & excluded_set
    return {
        "evidence_source_ids_unique": len(evidence_source_ids),
        "accounted_canonical": len(accounted_canonical),
        "accounted_excluded": len(accounted_excluded),
        "accounted_total": len(accounted_canonical | accounted_excluded),
        "unaccounted": len(evidence_source_ids - canonical_ids - excluded_set),
        "multi_accounted_conflict": len(multi_conflict),
        "excluded_without_evidence": len(excluded_set - evidence_source_ids),
        "excluded_foreign_run": excluded_foreign_run,
        "excluded_foreign_event": excluded_foreign_event,
        "excluded_foreign_source_hash": excluded_foreign_hash,
    }


def _restore_snapshot_grouped_period_provenance(rows: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    """Restore missing legacy period provenance from the immutable matching DOM snapshots.

    This is intentionally evidence-only: a period is restored only when the saved DOM
    exposes a grouped-market column heading for the same saved cell path.
    """
    match = re.fullmatch(r"raw_before_dedupe_run_(.+)\.jsonl", path.name)
    if not match:
        return rows
    # Non-grouped recovery requires the current capture schema to bind every
    # row to its period scope as well as immutable lineage.  Partial legacy
    # evidence is deliberately replayed unchanged and remains fail-closed.
    modern_lineage = bool(rows) and all(
        row.get("run_id") and row.get("event_id") and row.get("source_hash")
        and row.get("raw_record_id") and row.get("period_scope_id") for row in rows
    )
    snapshots = sorted((path.parent.parent / "snapshots").glob(f"tab_run_{match.group(1)}_*.html"))
    if not snapshots:
        return rows
    class Node:
        def __init__(self, tag: str, attrs: dict[str, str], parent: Node | None) -> None:
            self.tag, self.attrs, self.parent, self.children, self.data = tag, attrs, parent, [], []
            if parent:
                parent.children.append(self)

    class Tree(HTMLParser):
        def __init__(self) -> None:
            super().__init__(); self.root = Node("root", {}, None); self.current = self.root
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.current = Node(tag, {key: value or "" for key, value in attrs}, self.current)
        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            Node(tag, {key: value or "" for key, value in attrs}, self.current)
        def handle_endtag(self, tag: str) -> None:
            node = self.current
            while node.parent and node.tag != tag:
                node = node.parent
            self.current = node.parent if node.parent else self.root
        def handle_data(self, data: str) -> None:
            self.current.data.append(data)

    def has_class(node: Node, name: str) -> bool:
        return name in node.attrs.get("class", "").split()

    def descendants(node: Node) -> list[Node]:
        found: list[Node] = []
        for child in node.children:
            found.append(child); found.extend(descendants(child))
        return found

    def text(node: Node) -> str:
        data = [*node.data, *(piece for child in descendants(node) for piece in child.data)]
        return " ".join("".join(data).split())

    def first(node: Node, class_name: str) -> Node | None:
        return next((item for item in descendants(node) if has_class(item, class_name)), None)

    def normalized_odds(value: str) -> str:
        try:
            return f"{float(value.replace(',', '.')):.2f}"
        except ValueError:
            return value.replace(",", ".")

    evidence_by_key: dict[tuple[str, str, str, str], list[str]] = {}
    recovered: list[dict[str, Any]] = []
    for snapshot in snapshots:
        tab_match = re.fullmatch(r"tab_run_.+_\d+_(.+)\.html", snapshot.name)
        if not tab_match:
            continue
        tree = Tree(); tree.feed(snapshot.read_text(encoding="utf-8", errors="replace"))
        # Non-grouped markets use one lineSelection per real selection.  Read
        # each row atomically so a label, its price, and its market title cannot
        # bleed across neighbours.
        for box in (() if not modern_lineage else (node for node in descendants(tree.root) if has_class(node, "marketBox") and not has_class(node, "is-groupedMarket"))):
            title_node = first(box, "marketBox_headTitle")
            market_title = text(title_node) if title_node else ""
            if not market_title or "handicap" not in market_title.casefold():
                continue
            for line in (node for node in descendants(box) if has_class(node, "marketBox_lineSelection")):
                label_node = first(line, "marketBox_label")
                selection = text(label_node) if label_node else ""
                buttons = [node for node in descendants(line) if node.tag == "button" and "is-odd" in node.attrs.get("class", "")]
                if not selection or len(buttons) != 1:
                    continue
                odds_match = re.search(r"([1-9]\d{0,2}(?:[.,]\d{1,2})?)", text(buttons[0]))
                if not odds_match or float(odds_match.group(1).replace(',', '.')) <= 1.0:
                    continue
                odds = normalized_odds(odds_match.group(1))
                # Historical decimal-only captures are complete already.  This
                # recovery is reserved for evidence-backed integer handicap cells
                # which old capture regexes could not serialize.
                if not re.fullmatch(r"\d+", odds_match.group(1)):
                    continue
                key = (tab_match.group(1), market_title, selection, odds)
                if any((str(row.get("active_tab") or row.get("tab_name") or ""), str(row.get("market") or ""), str(row.get("selection") or ""), normalized_odds(str(row.get("odds") or ""))) == key for row in rows + recovered):
                    continue
                template = next((row for row in rows if str(row.get("active_tab") or row.get("tab_name") or "") == tab_match.group(1) and str(row.get("market") or "") == market_title), None)
                if template is None:
                    continue
                fingerprint = "|".join(key)
                source_id = "replay_html:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
                row = dict(template)
                row.update({"selection": selection, "odds": odds, "raw": selection + " " + odds,
                            "raw_record_id": source_id, "source_raw_record_ids": [source_id],
                            "source_index": source_id, "replay_html_recovered": True})
                recovered.append(row)
        for box in (node for node in descendants(tree.root) if has_class(node, "marketBox") and has_class(node, "is-groupedMarket")):
            title_node = first(box, "marketBox_headTitle")
            market_title = text(title_node) if title_node else ""
            headings = [text(node) for node in descendants(box) if has_class(node, "marketBox_itemValue") and text(node)]
            if not headings:
                continue
            for line in (node for node in descendants(box) if has_class(node, "marketBox_lineSelection")):
                label_node = first(line, "marketBox_label")
                selection = text(label_node) if label_node else ""
                list_node = first(line, "marketBox_list")
                if not selection or not list_node:
                    continue
                items = [node for node in list_node.children if has_class(node, "marketBox_item")]
                for index, item in enumerate(items):
                    if index >= len(headings):
                        continue
                    odds_match = re.search(r"([1-9]\d?[.,]\d{2})", text(item))
                    if odds_match:
                        key = (tab_match.group(1), market_title, selection, normalized_odds(odds_match.group(1)))
                        evidence_by_key.setdefault(key, []).append(headings[index])
    restored: list[dict[str, Any]] = []
    for source_row in rows:
        key = (str(source_row.get("active_tab") or source_row.get("tab_name") or ""), str(source_row.get("market") or ""),
               str(source_row.get("selection") or ""), normalized_odds(str(source_row.get("odds") or "")))
        headings = evidence_by_key.get(key, [])
        row = source_row
        if headings:
            row = dict(source_row)
            heading = headings.pop(0)
            row["period_hint"] = heading
            row["column_heading"] = heading
            instance_id = str(row.get("market_instance_id") or "")
            if "|column:" not in instance_id:
                row["market_instance_id"] = instance_id.replace("|row#", "|column:" + re.sub(r"\s+", ".", heading) + "|row#", 1)
        restored.append(row)
    return restored + recovered


def replay_real_prematch(path: Path = REAL_RUN_JSONL) -> dict[str, Any]:
    rows = _restore_snapshot_grouped_period_provenance(load_real_prematch_fixture(path), path)
    # Observation transport order is not capture chronology. Modern captures
    # retain the original source_index; never replace it with a shuffled file
    # position before selecting representatives of the same displayed offer.
    if rows and all(isinstance(row.get("source_index"), int) for row in rows):
        rows.sort(key=lambda row: (row["source_index"], str(row.get("raw_record_id") or "")))
    # Preserve the saved raw file untouched, but never replay accidental
    # readonly bet-slip UI copies as canonical MyCombi odds.
    rows = [row for row in rows if not _is_mycombi_betslip_ui_row(row)]
    kickoff, kickoff_source = _saved_capture_kickoff(path)
    home_team, away_team = _capture_teams(rows)
    saved_components = [dict(row.get("mycombi_component") or {}) for row in rows if row.get("record_type") == "MYCOMBI_COMPONENT"]
    saved_combination = next((dict(row.get("mycombi_combination") or {}) for row in rows if row.get("record_type") == "MYCOMBI_COMBINATION"), None)
    mycombi_state = validate_mycombi_state_for_event(
        {"components": saved_components, "combination": saved_combination}, home_team, away_team,
        str(rows[0].get("run_id") or "") if rows else "", str(rows[0].get("event_id") or "") if rows else "",
        str(rows[0].get("source_hash") or "") if rows else "",
    )
    if mycombi_state.get("rejected"):
        rows = [row for row in rows if not str(row.get("record_type") or "").startswith("MYCOMBI_")]
    for row in rows:
        for candidate in row.get("period_evidence_candidates") or []:
            period, reason = classify_period_evidence(candidate)
            candidate["evidence_period"] = period
            candidate["evidence_period_reason"] = reason
    evidence_source_ids = {
        str(candidate.get("raw_record_id"))
        for row in rows for candidate in (row.get("period_evidence_candidates") or [])
        if candidate.get("raw_record_id")
    }
    # Preserve legacy replay policy while applying the corrected, explicit source-
    # incomplete diagnostic policy to the two audited real-use runs.
    replay_id = path.name.removeprefix("raw_before_dedupe_run_").removesuffix(".jsonl")
    source_incomplete_enabled = replay_id in (FULL_USABLE_SOURCE_INCOMPLETE_RUNS | {
        "1785406931_13112", "1785407658_13112"})
    parsed: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    for source_index, row in enumerate(rows, 1):
        headerless_recovery = None
        if not row.get("market"):
            headerless_recovery = recover_headerless_top_offer(
                row.get("selection") or "", row.get("tab_name") or "",
                row.get("market_instance_id") or "",
                home_team, away_team,
            )
            if headerless_recovery is None:
                headerless_recovery = headerless_top_card_exclusion(
                    row.get("selection") or "", row.get("tab_name") or "", row.get("market_instance_id") or "")
            if headerless_recovery is None:
                unresolved.append({"MARKET": "NO_HEADER_" + str(row.get("tab_name", "")),
                                   "RAW": row.get("raw", ""), "REASON": "MISSING_MARKET_HEADER"})
                continue
        record, issue = parse_market_record(
            native_team_names=row.get("native_team_names"),
            category=row.get("category") or row.get("tab_name") or "",
            market_title=(headerless_recovery or {}).get("market_title", row.get("market") or ""),
            raw_selection=(headerless_recovery or {}).get("raw_selection", row.get("selection") or ""),
            odds_str=row.get("odds") or "", raw_text=row.get("raw") or "",
            section_title=row.get("section_title") or "", ancestor_title=row.get("ancestor_title") or "",
            period_hint=row.get("period_hint") or "", main_tab=row.get("active_tab") or row.get("tab_name") or "",
            settlement_scope_hint=row.get("settlement_scope_hint") or "", line_hint=row.get("line_hint") or "",
            participant_hint=(headerless_recovery or {}).get("participant_hint", row.get("participant_hint")),
            handicap_kind_hint=row.get("handicap_kind") or "", market_instance_id=row.get("market_instance_id") or "",
            home_team=home_team, away_team=away_team, container_id=_capture_container_identity(row),
        )
        if record and (headerless_recovery or {}).get("unrecognized_top_card"):
            neutralize_unrecognized_top_card(record)
        if record:
            record.update({"capture_id": row.get("capture_id") or "", "source_index": row.get("source_index", source_index),
                           "run_id": row.get("run_id") or "", "event_id": row.get("event_id") or "",
                           "source_hash": row.get("source_hash") or "", "raw_record_id": row.get("raw_record_id") or "",
                           "source_raw_record_ids": list(row.get("source_raw_record_ids") or ([] if not row.get("raw_record_id") else [row.get("raw_record_id")])),
                           "MARKET_INSTANCE_ID": record.get("MARKET_INSTANCE_ID") or row.get("market_instance_id") or "",
                           "DOM_PATH": row.get("dom_path") or row.get("container_id") or "",
                           "SECTION_PATH": row.get("heading_path") or row.get("section_path") or row.get("ancestor_title") or "",
                           "ACTIVE_TAB": row.get("active_tab") or row.get("tab_name") or "",
                           "ACTIVE_SUBTAB": row.get("active_subtab") or "",
                           "SOURCE_VISIBILITY": row.get("visibility") or row.get("source_visibility") or "VISIBLE",
                           "RENDER_STATE": row.get("render_state") or "",
                           "SCROLL_POSITION": row.get("scroll_position") or "",
                           "PERIOD_SCOPE_ID": row.get("period_scope_id") or "",
                           "ROW_ID": row.get("row_id") or "",
                           "COLUMN_ID": row.get("column_id") or "",
                           "NATIVE_SELECTION_ID": row.get("native_selection_id") or ""})
            attach_structural_provenance(record, row)
            if not row.get("period_scope_id"):
                record["_legacy_capture_schema"] = True
            parsed.append(record)
        if issue:
            unresolved.append(issue)
    unique, unresolved = _dedupe_records_preserving_order(parsed, unresolved)
    source_identity_representative_count = len(unique)
    for record in unique:
        record.pop("_legacy_capture_schema", None)
    handicap_audit = analyze_handicap_completeness(unique)
    source_incomplete_rows: list[dict[str, Any]] = []
    source_incomplete_instances: set[str] = set()
    excluded_lineage: list[dict[str, Any]] = []
    excluded_handicap_record_ids = handicap_audit["excluded_record_ids"]
    core_postprocessing_excluded_records = [
        record for record in unique if id(record) in excluded_handicap_record_ids
    ]
    core_postprocessing_excluded_source_ids = {
        str(source_id) for record in core_postprocessing_excluded_records
        for source_id in record.get("source_raw_record_ids") or
        ([record["raw_record_id"]] if record.get("raw_record_id") else [])
    }
    if handicap_audit["incomplete_instances"]:
        for entry in handicap_audit["incomplete_instances"]:
            records = entry["records"]
            issue = {"INCOMPLETE_INSTANCE_ID": entry["incomplete_instance_id"], "MARKET": entry["market"],
                     "RAW": " | ".join(str(record.get("RAW") or "") for record in records),
                     "REASON": "SOURCE_INCOMPLETE_MARKET_INSTANCE", "REPRESENTATION_COUNT": entry["representation_count"],
                     "SOURCE_RAW_RECORD_IDS": entry["source_raw_record_ids"], "SOURCE_TABS": entry["source_tabs"]}
            if source_incomplete_enabled:
                source_incomplete_instances.add(entry["incomplete_instance_id"])
                source_incomplete_rows.append(issue)
            else:
                unresolved.append({**issue, "REASON": "INCOMPLETE_MARKET_ROW"})
        retained: list[dict[str, Any]] = []
        for record in unique:
            if id(record) not in handicap_audit["excluded_record_ids"]:
                retained.append(record)
                continue
            source_ids = list(record.get("source_raw_record_ids") or
                               ([record["raw_record_id"]] if record.get("raw_record_id") else []))
            evidence_ids = [source_id for source_id in source_ids if source_id in evidence_source_ids]
            if not evidence_ids:
                continue
            excluded_lineage.append({
                "raw_record_id": evidence_ids[0],
                "source_raw_record_ids": evidence_ids,
                "run_id": record.get("run_id") or "",
                "event_id": record.get("event_id") or "",
                "source_hash": record.get("source_hash") or "",
                "period_scope_id": record.get("PERIOD_SCOPE_ID") or "",
                "market_instance_id": record.get("MARKET_INSTANCE_ID") or "",
                "row_id": record.get("ROW_ID") or "",
                "column_id": record.get("COLUMN_ID") or "",
                "native_selection_id": record.get("NATIVE_SELECTION_ID") or "",
                "market": record.get("MARKET") or "",
                "selection": record.get("SELECTION") or "",
                "exclusion_stage": "REPLAY_HANDICAP_COMPLETENESS",
                "exclusion_reason_code": "HANDICAP_COMPLETENESS_EXCLUSION",
                "exclusion_reason_detail": "incomplete " + str(record.get("HANDICAP_KIND") or "THREE_WAY") + " handicap instance",
            })
        unique = retained
    period_resolution = resolve_periods_from_lineage(unique, rows, excluded_lineage)
    derived_normalization = derive_market_normalization(unique, home_team, away_team)
    unique, semantic_quarantine_rows = partition_semantic_records(unique)
    semantic_quarantine = semantic_quarantine_ledger(semantic_quarantine_rows)
    player_prop_quarantine = [row for row in semantic_quarantine if row["scope"] == "PLAYER_PROP"]
    match_market_quarantine = [row for row in semantic_quarantine if row["scope"] == "MATCH_MARKET"]
    optional_statistics_quarantine = [row for row in semantic_quarantine if row["scope"] == "OPTIONAL_STATISTICS"]
    period_counts = Counter(record.get("PERIOD", "UNKNOWN") for record in unique)
    reasons = Counter(item.get("REASON", "") for item in unresolved)
    completeness = completeness_breakdown(
        detected_tabs=len({str(row.get("active_tab") or row.get("tab_name") or "") for row in rows}),
        scanned_tabs=len({str(row.get("active_tab") or row.get("tab_name") or "") for row in rows}),
        # A replay can collapse equivalent tab representations.  The capture
        # was complete when every raw row parsed, even if fewer canonical rows
        # survive dedupe.
        raw_records=len(rows), parsed_records=len(parsed), unknown_periods=period_counts.get("UNKNOWN", 0),
        incomplete_instances=len(source_incomplete_instances),
        excluded_rows=sum(int(row.get("REPRESENTATION_COUNT") or 0) for row in source_incomplete_rows),
    )
    exhaustive_ready = "NO" if period_counts.get("UNKNOWN", 0) or source_incomplete_rows or semantic_quarantine else "YES"
    full_usable_ready = "YES" if not unresolved else "NO"
    production_accounting = production_accounting_report(
        raw_rows=rows, parsed_records=parsed,
        source_identity_representative_count=source_identity_representative_count,
        home_team=home_team, away_team=away_team, path=path,
        core_usable_representative_count=len(unique),
        core_semantic_quarantined_count=len(semantic_quarantine_rows),
        core_postprocessing_excluded_count=len(core_postprocessing_excluded_records),
        upstream_other_excluded_count=len(core_postprocessing_excluded_source_ids),
        unresolved_count=len(unresolved),
    )
    quality = semantic_quality_report(
        parsed_records=len(parsed), accepted_records=len(unique), quarantined_rows=semantic_quarantine_rows,
        completeness=completeness, full_usable_ready=full_usable_ready, exhaustive_ready=exhaustive_ready,
    )
    return {"raw_records": len(rows), "parsed_records": len(parsed), "odds": unique,
            "unresolved": unresolved, "period_counts": dict(sorted(period_counts.items())),
            "period_unknown": period_counts.get("UNKNOWN", 0), "unresolved_count": len(unresolved),
            "unresolved_reasons": dict(sorted(reasons.items())),
            "source_incomplete_instances": sorted(source_incomplete_instances),
            "source_incomplete_rows": source_incomplete_rows, "excluded_rows": len(source_incomplete_rows),
            "excluded_lineage": excluded_lineage,
            "semantic_quarantine": semantic_quarantine,
            "player_prop_quarantine": player_prop_quarantine,
            "match_market_quarantine": match_market_quarantine,
            "optional_statistics_quarantine": optional_statistics_quarantine,
            "period_resolution": period_resolution,
            "derived_normalization": derived_normalization,
            "exhaustive_ready": exhaustive_ready, "full_usable_ready": full_usable_ready,
            "analysis_ready": "YES" if full_usable_ready == "YES" else "NO",
            "analysis_scope": "FULL_USABLE_EXCLUDING_SOURCE_INCOMPLETE" if full_usable_ready == "YES" else "CLEAN_CORE_BLOCKED",
            "quality_dimensions": quality,
            "production_accounting": production_accounting,
            "mycombi_components": mycombi_state["components"], "mycombi_combination": mycombi_state["combination"],
            "mycombi_rejected": mycombi_state.get("rejected") or [],
            "kickoff": kickoff, "kickoff_source": kickoff_source, "completeness": completeness}
