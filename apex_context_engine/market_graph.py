from __future__ import annotations

from collections import defaultdict
from typing import Iterable
import re
import unicodedata

from .devig import devig, implied_probabilities
from .models import FairMarket, OddRecord, ParsedPacket

_OUTCOMES = {
    "1X2": {"HOME", "DRAW", "AWAY"},
    "DNB": {"HOME", "AWAY"},
    "GOALS_OU": {"OVER", "UNDER"},
    "BTTS": {"YES", "NO", "TAK", "NIE"},
    "TEAM_TOTALS_HOME": {"OVER", "UNDER"},
    "TEAM_TOTALS_AWAY": {"OVER", "UNDER"},
}

_VALID_SCORER_SCOPES = {
    "ANYTIME", "FIRST_GOAL", "LAST_GOAL", "TWO_OR_MORE_GOALS", "THREE_OR_MORE_GOALS",
}


def _same_semantic_text(left: str, right: str) -> bool:
    return _semantic_text(left) == _semantic_text(right)


def _named_player(value: str) -> bool:
    """Accept a concrete personal name, never a binary or free-form selection."""
    words = _semantic_text(value).split()
    name_word = re.compile(r"[a-z]+(?:[-'][a-z]+)*\.?$")
    return len(words) >= 2 and all(name_word.fullmatch(word) for word in words) and not any(
        word in {"yes", "no", "tak", "nie", "none", "brak"} for word in words
    )


_NOT_A_PLAYER = {"yes", "no", "tak", "nie", "none", "brak", "remis", "draw", "home", "away",
                 "over", "under", "powyzej", "ponizej", "nikt", "zaden", "inny", "other", "gol", "gole"}


def _single_name_player(record: OddRecord) -> bool:
    """A one-word player name (Raphinha, Rodri) proven by its own row.

    Accepted only when the explicit row-local participant and the selection are
    the same single name, that name is printed on the priced button and it is
    neither a reserved outcome word nor an event team.
    """
    word = _semantic_text(record.selection)
    return (bool(re.fullmatch(r"[a-z]{3,}(?:[-'][a-z]+)*", word)) and word not in _NOT_A_PLAYER
            and _same_semantic_text(record.selection, record.participant)
            and word in _semantic_text(record.raw).split()
            and not any(_same_semantic_text(record.selection, team) for team in record.event_teams))


def _expected_scorer_scope(record: OddRecord) -> str:
    market = _semantic_text(record.market)
    if "pierwsz" in market and ("strzelec" in market or "scorer" in market):
        return "FIRST_GOAL"
    if "ostatni" in market and ("strzelec" in market or "scorer" in market):
        return "LAST_GOAL"
    return ""


def _scorer_safety_reason(record: OddRecord) -> str:
    """Closed, evidence-based gate for player-scoring propositions.

    This proves only that the existing packet describes one player, one event
    team, one scope and a binary scorer settlement; it does not model or price
    the player market.
    """
    if not (_named_player(record.selection) and _named_player(record.participant)) \
            and not _single_name_player(record):
        return "SCORER_PLAYER_IDENTITY_MISSING"
    if not _same_semantic_text(record.selection, record.participant):
        return "SCORER_PLAYER_IDENTITY_CONFLICT"
    if not record.raw or _semantic_text(record.selection) not in _semantic_text(record.raw):
        return "SCORER_RAW_EVIDENCE_CONFLICT"
    if not record.owner:
        return "SCORER_OWNER_MISSING"
    if record.event_teams and not any(_same_semantic_text(record.owner, team) for team in record.event_teams):
        return "SCORER_OWNER_OUTSIDE_EVENT"
    if record.period not in {"FULL_TIME", "1ST_HALF", "2ND_HALF"}:
        return "SCORER_PERIOD_INVALID"
    if record.scorer_scope not in _VALID_SCORER_SCOPES:
        return "AMBIGUOUS_GOALSCORER_SCOPE"
    expected_scope = _expected_scorer_scope(record)
    if expected_scope and record.scorer_scope != expected_scope:
        return "SCORER_SCOPE_CONFLICT"
    if record.settlement != "WIN_LOSE":
        return "SCORER_SETTLEMENT_INVALID"
    return ""


def _semantic_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", str(value or "").replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode().casefold().split())


def _market_domain(record: OddRecord) -> str:
    category = _semantic_text(record.category)
    metric = _semantic_text(f"{record.market} {record.category}")
    statistical = "statyst" in category or "statistics" in category
    metrics = (
        ("SHOTS_ON_TARGET", ("strzaly celne", "celnych strzal", "shots on target")),
        ("CORNERS", ("rzuty rozne", "rzutow roznych", "rzut rozny", " rozny", "rozne ", "corner")),
        ("SHOTS", ("strzal", "shot")),
        ("FOULS", ("faul", "foul")),
        ("OFFSIDES", ("spalon", "offside")),
        ("CARDS", ("kartk", "card")),
    )
    for name, tokens in metrics:
        if statistical or any(token in metric for token in tokens):
            if any(token in metric for token in tokens):
                return f"STATISTICS:{name}"
    if statistical:
        return "STATISTICS:OTHER"
    if record.family in {"1X2", "DNB", "HANDICAP_EUROPEAN", "HANDICAP_ASIAN"}:
        return "FOOTBALL_RESULT"
    if record.family in {"GOALS_OU", "BTTS", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"}:
        return "FOOTBALL_GOALS"
    if record.family in {"GOALSCORER", "PLAYER_PROP", "PLAYER_COMBINATION"}:
        return "PLAYER_PROP"
    return f"OTHER:{record.family}"


def _identity(record: OddRecord) -> tuple[str, ...]:
    line = record.line
    if record.family.startswith("HANDICAP_") and line:
        try:
            # Fair markets use a canonical HOME axis, but never discard the
            # sign.  AWAY lines are the inverse representation of that axis.
            signed = float(line)
            outcome = record.canonical_outcome or record.selection
            line = f"{-signed if outcome == 'AWAY' else signed:g}"
        except ValueError:
            pass
    owner = record.owner if record.family in {"TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"} else ""
    return (
        record.family, record.market.strip().casefold(), record.period, owner, line,
        record.handicap_kind, record.handicap_taxonomy, record.settlement, _market_domain(record),
    )


def _expected(record: OddRecord) -> set[str] | None:
    market_key = record.market.casefold()
    compound = any(marker in market_key for marker in (
        "wynik i ", "wynik meczu &", "podwójna szansa &", "obie połowy",
        "w 1. i 2.", "z rzutu karnego", "obie drużyny zdobywają gole -",
    ))
    if compound:
        return None
    if record.family in {"HANDICAP_EUROPEAN", "HANDICAP_ASIAN"}:
        return {"HOME", "AWAY"} if record.handicap_kind == "TWO_WAY" else {"HOME", "DRAW", "AWAY"}
    values = _OUTCOMES.get(record.family)
    if record.family == "BTTS" and values:
        return {"YES", "NO"} if record.selection in {"YES", "NO"} else {"TAK", "NIE"}
    return values


def build_fair_markets(packet: ParsedPacket) -> tuple[list[FairMarket], list[str]]:
    grouped: dict[tuple[str, ...], list[OddRecord]] = defaultdict(list)
    warnings: list[str] = []
    for record in packet.odds:
        domain = _market_domain(record)
        if domain.startswith("STATISTICS:") or domain == "PLAYER_PROP":
            warnings.append(f"NON_FOOTBALL_FAIR_MARKET_REJECTED:{domain}:{record.family}:{record.market}")
            continue
        grouped[_identity(record)].append(record)

    result: list[FairMarket] = []
    for key in sorted(grouped):
        records = grouped[key]
        best: dict[str, OddRecord] = {}
        for record in sorted(records, key=lambda r: (r.selection, -r.odds, r.source_index)):
            if record.selection not in best or record.odds > best[record.selection].odds:
                best[record.selection] = record
        first = records[0]
        expected = _expected(first)
        if expected is None:
            warnings.append(f"DEVIG_UNSUPPORTED_FAMILY:{first.family}:{first.period}:{first.market}")
            continue
        if set(best) != expected:
            warnings.append(f"INCOMPLETE_MARKET:{first.family}:{first.period}:{first.market}:{','.join(sorted(set(best)))}")
            continue
        distinct = [best[name] for name in sorted(best)]
        source_odds = [r.odds for r in distinct]
        raw = implied_probabilities(source_odds)
        preferred = "SHIN" if first.family == "1X2" else "POWER"
        probs, method, detail, method_warnings = devig(source_odds, preferred)
        warnings.extend(method_warnings)
        label = "|".join(key[:-1])
        result.append(FairMarket(
            key=label, family=first.family, market=first.market, period=first.period, owner=key[3],
            line=key[4], handicap_kind=first.handicap_kind, handicap_taxonomy=first.handicap_taxonomy,
            settlement=first.settlement, method=method, method_detail=detail,
            selections={r.selection: round(p, 12) for r, p in zip(distinct, probs)},
            raw_implied={r.selection: round(p, 12) for r, p in zip(distinct, raw)},
            source_odds={r.selection: r.odds for r in distinct}, overround=round(sum(raw), 12),
        ))
    return result, sorted(set(warnings))


def canonical_signature(record: OddRecord) -> str:
    outcome = record.canonical_outcome or record.selection
    scorer_scope = record.scorer_scope if record.family in {"GOALSCORER", "PLAYER_COMBINATION"} else ""
    signature = "|".join((
        _market_domain(record), record.period, record.family, record.market.strip().casefold(), record.owner, outcome, record.line,
        # Capture location is provenance, never a settlement predicate.  The
        # same offer shown in Top and Wynik must retain separate lineage yet
        # share its canonical semantic identity.
        record.handicap_kind, record.handicap_taxonomy, record.settlement, scorer_scope,
    ))
    if record.family == "PLAYER_PROP":
        # SCORE_AND_TOTAL_OVER describes an action, not the named player.
        # Different players on one team never share a settlement event.
        signature += "|" + record.participant.strip() + "|" + record.scorer_scope
    return signature


def _safe_equivalence_keys(record: OddRecord) -> list[tuple[str, str]]:
    if record.family == "PLAYER_PROP" and not record.participant.strip():
        return []
    keys = [(canonical_signature(record), "EXACT_DUPLICATE_FULL_SEMANTIC_SIGNATURE")]
    outcome = record.canonical_outcome or record.selection
    # De Morgan on integer goals: NOT(total > 2.5) == total < 2.5.
    # Integer lines have a boundary/push and cannot use this rule.
    if (record.family == "COMPOUND_LOGIC" and record.settlement == "WIN_LOSE"
            and record.line == "2.5" and not record.owner
            and outcome in {"BTTS_OR_OVER_NO", "BTTS_NO_AND_UNDER"}):
        keys.append((f"FOOTBALL_GOALS|{record.period}|NOT_BTTS_AND_UNDER:2.5",
                     "DE_MORGAN_INTEGER_GOALS_HALF_LINE_2_5"))
    rule = f"1X2_{outcome}_EQ_HANDICAP_{outcome}_MINUS_0_5_TWO_WAY_SAME_PERIOD"
    domain = _market_domain(record)
    if (domain == "FOOTBALL_RESULT" and record.family == "1X2" and outcome == "DRAW"
            and record.settlement == "WIN_LOSE" and not record.line and not record.owner
            and record.period in {"FULL_TIME", "1ST_HALF", "2ND_HALF"}
            and _semantic_text(record.market) in {"wynik meczu", "wynik meczu (z wylaczeniem dogrywki)"}):
        keys.append((f"FOOTBALL_RESULT|{record.period}|RESULT_DRAW",
                     "1X2_DRAW_SAME_PERIOD_BINARY_RESULT"))
    if domain == "FOOTBALL_RESULT" and record.family == "1X2" and record.settlement == "WIN_LOSE" and outcome in {"HOME", "AWAY"}:
        keys.append((f"FOOTBALL_RESULT|{record.period}|RESULT_{outcome}", rule))
    if (domain == "FOOTBALL_RESULT" and record.family.startswith("HANDICAP_") and record.handicap_kind == "TWO_WAY"
            and record.line == "-0.5" and record.settlement == "NO_PUSH"
            and outcome in {"HOME", "AWAY"}):
        keys.append((f"FOOTBALL_RESULT|{record.period}|RESULT_{outcome}", rule))
    if (record.family == "DNB" and outcome in {"HOME", "AWAY"}
            and not record.line and record.settlement == "PUSH_ON_DRAW"):
        keys.append((f"{domain}|MATH_DNB_ZERO|{record.period}|{outcome}", "DNB_EQ_HANDICAP_0_0_SAME_OWNER_AND_PERIOD"))
    if (record.family.startswith("HANDICAP_") and record.handicap_kind == "TWO_WAY"
            and record.line == "0" and outcome in {"HOME", "AWAY"}
            and record.settlement == "PUSH_POSSIBLE"):
        keys.append((f"{_market_domain(record)}|MATH_DNB_ZERO|{record.period}|{outcome}", "DNB_EQ_HANDICAP_0_0_SAME_OWNER_AND_PERIOD"))
    return keys


PRICE_CONTRADICTION_RATIO = 0.50


def equivalence_price_contradictions(records: Iterable[OddRecord]) -> list[dict]:
    """Proved-equivalence groups whose prices contradict a common settlement."""
    grouped: dict[tuple[str, str], list[OddRecord]] = defaultdict(list)
    for record in records:
        if record.family in {"GOALSCORER", "PLAYER_COMBINATION"}:
            continue
        if (record.canonical_outcome or "").startswith("COMPOUND_RAW="):
            continue
        for key, rule in _safe_equivalence_keys(record):
            if rule != "EXACT_DUPLICATE_FULL_SEMANTIC_SIGNATURE":
                grouped[(key, rule)].append(record)
    rows = []
    for signature, rule in sorted(grouped):
        items = grouped[(signature, rule)]
        high, low = max(x.odds for x in items), min(x.odds for x in items)
        if low > 0 and high / low - 1.0 > PRICE_CONTRADICTION_RATIO:
            rows.append({
                "signature": signature, "allowlist_rule": rule,
                "price_ratio": round(high / low, 6),
                "markets": sorted({(x.market, x.category, x.odds) for x in items}),
            })
    return rows


def best_price_alerts(records: Iterable[OddRecord], min_gain_percent: float = 0.01) -> list[dict]:
    grouped: dict[tuple[str, str], list[OddRecord]] = defaultdict(list)
    for record in records:
        if record.family in {"GOALSCORER", "PLAYER_COMBINATION"}:
            continue
        if (record.canonical_outcome or "").startswith("COMPOUND_RAW="):
            continue
        for key in _safe_equivalence_keys(record):
            grouped[key].append(record)
    alerts: list[dict] = []
    seen_groups = set()
    for signature, rule in sorted(grouped):
        items = grouped[(signature, rule)]
        group_fingerprint = tuple(sorted((x.source_index, x.market, x.category, x.odds) for x in items))
        if group_fingerprint in seen_groups:
            continue
        seen_groups.add(group_fingerprint)
        representations = {(x.market, x.category, x.odds) for x in items}
        if len(representations) < 2:
            continue
        ordered = sorted(items, key=lambda x: (-x.odds, x.market, x.category, x.source_index))
        best = ordered[0]
        worse = [x for x in ordered[1:] if x.odds < best.odds]
        if not worse:
            continue
        # A >50% jump inside one bookmaker's book cannot be a price difference
        # for the same settlement: it proves that one side was classified
        # wrongly (live 2026-09-28: an interval "Wynik" 7.75 read as the FT
        # result 3.73).  Such groups are never offered as better prices;
        # equivalence_price_contradictions() reports them explicitly.
        if any((best.odds / item.odds - 1.0) > PRICE_CONTRADICTION_RATIO for item in worse):
            continue
        copies = []
        for item in worse:
            gain = (best.odds / item.odds - 1.0) * 100.0
            if gain >= min_gain_percent:
                copies.append({"market": item.market, "category": item.category, "odds": item.odds, "gain_percent": round(gain, 6)})
        if copies:
            alerts.append({
                "signature": signature,
                "canonical_settlement_event": signature if "|RESULT_" in signature else None,
                "safety": "PASS_EXACT_MATHEMATICAL_EQUIVALENCE" if "|RESULT_" in signature else "PASS_EXACT_SEMANTIC_IDENTITY",
                "allowlist_rule": rule,
                "best": {"market": best.market, "category": best.category, "odds": best.odds},
                "worse_copies": copies,
            })
    return alerts


def semantic_safety_quarantine(records: Iterable[OddRecord]) -> list[dict]:
    rows = []
    for record in records:
        if record.family in {"GOALSCORER", "PLAYER_COMBINATION"}:
            proof = _captured_player_contract(record)
            if proof == "":
                continue
            if proof:
                rows.append({"source_index": record.source_index, "family": record.family,
                             "market": record.market, "selection": record.selection,
                             "source_raw_record_ids": list(record.source_raw_record_ids),
                             "raw_evidence": record.raw, "reason": proof})
                continue
        if record.family == "GOALSCORER":
            reason = _scorer_safety_reason(record)
            if not reason:
                continue
            rows.append({"source_index": record.source_index, "family": record.family,
                         "market": record.market, "selection": record.selection,
                         "participant": record.participant, "owner": record.owner,
                         "period": record.period, "scorer_scope": record.scorer_scope,
                         "settlement": record.settlement,
                         "source_raw_record_ids": list(record.source_raw_record_ids),
                         "raw_evidence": record.raw, "reason": reason})
        elif record.family == "PLAYER_COMBINATION":
            rows.append({"source_index": record.source_index, "family": record.family,
                         "market": record.market, "selection": record.selection,
                         "reason": "AMBIGUOUS_GOALSCORER_SCOPE"})
    return sorted(rows, key=lambda row: (row["source_index"], row["market"], row["selection"]))


def _captured_player_contract(record: OddRecord) -> str | None:
    """Verify rich capture contracts instead of applying a single-scorer gate.

    Reparse the original selection and column identity with the closed source
    contracts. Team ownership is required only by a team-dependent predicate.
    None delegates compact/legacy records to the existing fail-closed checks.
    """
    if "xtra" in record.market.casefold():
        return "UNCONFIRMED_XTRA_PAYOUT_CONTRACT"
    if not record.source_raw_record_ids or not record.market_instance or len(record.event_teams) != 2:
        return None
    from parser import (parse_market_record, _player_goal_combination_contract,
                        _goal_assist_combination_mode, _pure_assist_combination_mode,
                        _is_scorer_assister_regular_time_title)
    title = _semantic_text(record.market)
    known = title in {"strzelcy", "strzelec", "strzelec gola lub jego zmiennik",
                      "strzelec i jego zmiennik", "zawodnik lub jego zmiennik strzeli gola (90 min)"}
    known = known or bool(_player_goal_combination_contract(record.market)
                          or _goal_assist_combination_mode(record.market)
                          or _pure_assist_combination_mode(record.market)
                          or _is_scorer_assister_regular_time_title(record.market))
    if not known:
        return None
    if record.owner and not any(_same_semantic_text(record.owner,t) for t in record.event_teams):
        return "SCORER_OWNER_OUTSIDE_EVENT"
    row, issue = parse_market_record(
        category=record.category, market_title=record.market,
        raw_selection=record.raw.rsplit(" ", 1)[0], odds_str=str(record.odds),
        raw_text=record.raw, section_title=record.owner,
        home_team=record.event_teams[0], away_team=record.event_teams[1],
        container_id=record.market_instance, market_instance_id=record.market_instance,
        participant_hint=record.participant or None,
        period_hint={"FULL_TIME":"90 min", "1ST_HALF":"1. połowa", "2ND_HALF":"2. połowa"}.get(record.period,""),
    )
    if issue or not row:
        return "PLAYER_CONTRACT_RAW_NOT_RESOLVABLE"
    for key, attribute in (("FAMILY","family"), ("SELECTION","selection"),
                           ("PARTICIPANT","participant"), ("SCORER_SCOPE","scorer_scope"),
                           ("LINE","line"), ("SETTLEMENT","settlement")):
        if not _same_semantic_text(row.get(key,""), getattr(record,attribute)):
            return "PLAYER_CONTRACT_CONFLICT:" + key
    if record.period not in {"FULL_TIME", "1ST_HALF", "2ND_HALF"}:
        return "SCORER_PERIOD_INVALID"
    return ""


def audit_equivalence(packet: ParsedPacket, alerts: list[dict]) -> dict:
    accepted, rejected = [], []
    by_lookup: dict[tuple[str, str, str], list[OddRecord]] = defaultdict(list)
    for record in packet.odds:
        by_lookup[(record.market, record.category, f"{record.odds:g}")].append(record)
    for index, group in enumerate(packet.equivalence_groups_raw):
        matched: list[OddRecord] = []
        unresolved_copies = 0
        for copy in group.get("COPIES", []) if isinstance(group.get("COPIES"), list) else []:
            try:
                odds_key = f"{float(str(copy.get('odds', '')).replace(',', '.')):g}"
            except ValueError:
                unresolved_copies += 1
                continue
            candidates = by_lookup.get((str(copy.get("market", "")), str(copy.get("category", "")), odds_key), [])
            source_ids = set(copy.get("source_raw_record_ids") or [])
            if source_ids and any(r.source_raw_record_ids for r in candidates):
                candidates = [r for r in candidates if source_ids == set(r.source_raw_record_ids)]
            # Legacy copies without lineage are only resolvable if the lookup
            # itself identifies one settlement. Never guess using declaration.
            elif len({canonical_signature(r) for r in candidates}) > 1:
                candidates = []
            if not candidates:
                unresolved_copies += 1
            matched.extend(candidates)
        signatures = sorted({canonical_signature(item) for item in matched})
        row = {"source_index": index, "declared_signature": group.get("SIGNATURE", ""), "matched_records": len(matched), "semantic_signatures": signatures, "unresolved_copies": unresolved_copies}
        common_keys = set(_safe_equivalence_keys(matched[0])) if matched else set()
        for item in matched[1:]:
            common_keys &= set(_safe_equivalence_keys(item))
        if common_keys and len(matched) >= 2 and not unresolved_copies:
            preferred = sorted(common_keys, key=lambda item: (0 if "|RESULT_" in item[0] else 1, item))[0]
            canonical_event, applied_rule = preferred
            row["result"] = "ACCEPTED"
            row["canonical_settlement_event"] = canonical_event
            row["allowlist_rules"] = sorted({rule for _, rule in common_keys})
            row["record_mappings"] = [_mapping_audit(item, canonical_event, applied_rule, True) for item in sorted(matched, key=lambda item: item.source_index)]
            accepted.append(row)
        else:
            row["result"] = "REJECTED_UNPROVEN_OR_MIXED_SEMANTICS"
            row["record_mappings"] = [_mapping_audit(item, None, None, False) for item in sorted(matched, key=lambda item: item.source_index)]
            rejected.append(row)
    return {
        "status": "PASS" if not rejected else "PASS_WITH_REJECTIONS",
        "independent_alert_count": len(alerts), "declared_groups_checked": len(packet.equivalence_groups_raw),
        "accepted_groups": accepted, "rejected_groups": rejected,
        "allowlist": [
            "EXACT_DUPLICATE_FULL_SEMANTIC_SIGNATURE",
            "1X2_HOME_EQ_HANDICAP_HOME_MINUS_0_5_TWO_WAY_SAME_PERIOD",
            "1X2_AWAY_EQ_HANDICAP_AWAY_MINUS_0_5_TWO_WAY_SAME_PERIOD",
            "1X2_DRAW_SAME_PERIOD_BINARY_RESULT",
            "DNB_EQ_HANDICAP_0_0_SAME_OWNER_AND_PERIOD",
            "DE_MORGAN_INTEGER_GOALS_HALF_LINE_2_5",
        ],
        "semantic_collision_alerts_suppressed": _collision_count(packet.odds),
    }


def _mapping_audit(record: OddRecord, canonical_event: str | None, rule: str | None, accepted: bool) -> dict:
    outcome = record.canonical_outcome or record.selection
    original_line = record.line
    canonical_line = original_line
    if record.family.startswith("HANDICAP_") and original_line:
        try:
            canonical_line = f"{-float(original_line) if outcome == 'AWAY' else float(original_line):g}"
        except ValueError:
            pass
    return {
        "SOURCE_RECORD_ID": f"ODD:{record.source_index}",
        "ORIGINAL_SEMANTIC_SIGNATURE": canonical_signature(record),
        "APPLIED_RULE_ID": rule,
        "CANONICAL_SETTLEMENT_EVENT": canonical_event,
        "MAPPING_RESULT": "MAPPED" if accepted else "REJECTED_UNPROVEN",
        "ORIGINAL_SIDE": outcome if outcome in {"HOME", "AWAY", "DRAW"} else "",
        "ORIGINAL_SIGNED_LINE": original_line,
        "CANONICAL_SIDE": "HOME_AXIS" if record.family.startswith("HANDICAP_") else outcome,
        "CANONICAL_SIGNED_LINE": canonical_line,
        "HANDICAP_KIND": record.handicap_kind,
        "SETTLEMENT": record.settlement,
    }


def _collision_count(records: Iterable[OddRecord]) -> int:
    grouped: dict[str, list[OddRecord]] = defaultdict(list)
    for record in records:
        if record.family not in {"GOALSCORER", "PLAYER_COMBINATION"} and not (record.canonical_outcome or "").startswith("COMPOUND_RAW="):
            grouped[canonical_signature(record)].append(record)
    return sum(1 for items in grouped.values() if len(items) > 1 and max(x.odds for x in items) / min(x.odds for x in items) - 1.0 > 0.50)


def build_market_graph(markets: list[FairMarket]) -> dict:
    nodes = [{"id": market.key, "family": market.family, "period": market.period, "owner": market.owner, "line": market.line, "settlement": market.settlement} for market in markets]
    relations = []
    buckets = {
        "RESULT_CHAIN": {"1X2", "DNB", "DOUBLE_CHANCE", "HANDICAP_EUROPEAN", "HANDICAP_ASIAN"},
        "GOAL_CHAIN": {"GOALS_OU", "BTTS", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"},
    }
    for relation, families in buckets.items():
        ids = sorted(node["id"] for node in nodes if node["family"] in families)
        if len(ids) >= 2:
            relations.append({"type": relation, "nodes": ids})
    periods: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for market in markets:
        periods[(market.family, market.owner, market.line)].append(market.key)
    for key in sorted(periods):
        ids = sorted(periods[key])
        if len({next(node["period"] for node in nodes if node["id"] == item) for item in ids}) >= 2:
            relations.append({"type": "PERIOD_CHAIN", "nodes": ids})
    return {"nodes": nodes, "relations": relations}
