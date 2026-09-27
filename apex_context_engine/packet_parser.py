from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from .models import OddRecord, ParsedPacket
from .semantic_resolver import resolve_semantics

_ASSIGN_RE = re.compile(r'^([A-Z0-9_]+)\s*=\s*(?:"(.*)"|([^;]*))\s*;$')
_BLOCK_RE = re.compile(r'(?m)^\s*(ODD|EQUIVALENCE_GROUP|UNRESOLVED|EXCLUDED_MARKET|SOURCE_INCOMPLETE|SEMANTIC_QUARANTINE)\s*\{(.*?)^\s*\}', re.DOTALL)
_HEADER_RE = re.compile(r'(?m)^\ufeff?\s*BETCLIC_FULL_ODDS_PACKET\s*\{(.*?)^\s*\}', re.DOTALL)
_REQUIRED_HEADER = ("MATCH", "COMPETITION")
_REQUIRED_ODD_KEYS = (
    "CATEGORY", "FAMILY", "MARKET", "PERIOD", "OWNER", "SELECTION", "LINE",
    "ODDS",
)
_VALID_PERIODS = {"FULL_TIME", "1ST_HALF", "2ND_HALF", "MATCH_INCLUDING_EXTRA_TIME"}


def _source_record_ids(value: str) -> tuple[str, ...]:
    """Preserve the upstream lineage order while discarding empty duplicates."""
    return tuple(dict.fromkeys(part.strip() for part in str(value or "").split(",") if part.strip()))


def _norm_words(value: str) -> str:
    return " ".join(value.casefold().replace("&", " & ").split())


def _double_chance_outcome(raw: str, home: str, away: str) -> str:
    value = _norm_words(raw.rsplit(" ", 1)[0])
    has_home, has_away = _norm_words(home) in value, _norm_words(away) in value
    has_draw = any(word in value for word in ("remis", "draw"))
    if has_home and has_draw and not has_away:
        return "1X"
    if has_home and has_away and not has_draw:
        return "12"
    if has_draw and has_away and not has_home:
        return "X2"
    return ""


def _compound_outcome(family: str, market: str, raw: str, home: str, away: str) -> str:
    """Closed parsing for compound rows; complete RAW is the evidence boundary."""
    market_key, value = _norm_words(market), raw.rsplit(" ", 1)[0].strip()
    if family == "FIRST_GOAL_TEAM" and ("wynik i kto" in market_key or "result and" in market_key):
        parts = [part.strip() for part in value.split("/", 1)]
        if len(parts) != 2:
            return ""
        result_text, first_text = _norm_words(parts[0]), _norm_words(parts[1])
        final = "HOME" if _norm_words(home) in result_text else "AWAY" if _norm_words(away) in result_text else "DRAW" if any(x in result_text for x in ("remis", "draw")) else ""
        first = "HOME" if _norm_words(home) in first_text else "AWAY" if _norm_words(away) in first_text else "NO_GOAL" if any(x in first_text for x in ("brak gola", "no goal")) else ""
        return f"FINAL_RESULT={final};FIRST_GOAL_TEAM={first}" if final and first else ""
    compound_markers = (" & ", " / ", " i kto ", "wynik i ", "wynik meczu &", "obie połowy", "w 1. i 2.")
    if any(marker in market_key or marker in _norm_words(value) for marker in compound_markers):
        return "COMPOUND_RAW=" + _norm_words(value).upper()
    return ""


class PacketParseError(ValueError):
    pass


def normalize_packet_text(text: str) -> str:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip() + "\n"


def _parse_assignments(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in body.splitlines():
        match = _ASSIGN_RE.match(raw_line.strip())
        if match:
            result[match.group(1)] = (match.group(2) if match.group(2) is not None else match.group(3)).strip()
    return result


def _decimal(value: str, field: str) -> float:
    normalized = value.strip().replace(" ", "").replace(",", ".")
    try:
        number = float(normalized)
    except ValueError as exc:
        raise ValueError(f"{field}_NOT_NUMERIC:{value}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field}_NOT_FINITE:{value}")
    return number


def _normal_line(value: str) -> str:
    if not value.strip():
        return ""
    number = _decimal(value, "LINE")
    if number == 0:
        number = 0.0
    return f"{number:g}"


def _collapse_record_errors(errors: list[str]) -> list[str]:
    grouped: Counter[tuple[str, str]] = Counter()
    retained: list[str] = []
    prefixes = {"ODD_MISSING_FIELDS", "ODD_EMPTY_FIELDS", "ODD_UNSUPPORTED_PERIOD", "TEAM_TOTAL_OWNER_MISSING", "LINE_REQUIRED"}
    for error in errors:
        parts = error.split(":", 2)
        if parts[0] in prefixes and len(parts) >= 2:
            detail = parts[2] if len(parts) == 3 else ""
            grouped[(parts[0], detail)] += 1
        else:
            retained.append(error)
    retained.extend(f"{prefix}:{detail}:COUNT={count}" if detail else f"{prefix}:COUNT={count}" for (prefix, detail), count in sorted(grouped.items()))
    return sorted(set(retained))


def parse_packet_text(text: str) -> ParsedPacket:
    normalized = normalize_packet_text(text)
    header_match = _HEADER_RE.search(normalized)
    if not header_match:
        raise PacketParseError("MISSING_BETCLIC_FULL_ODDS_PACKET_HEADER")

    header = _parse_assignments(header_match.group(1))
    warnings: list[str] = []
    errors = [f"MISSING_HEADER_FIELD:{key}" for key in _REQUIRED_HEADER if key not in header or not header[key]]
    odds: list[OddRecord] = []
    equivalence_groups: list[dict] = []
    quarantined_rows: list[dict] = []
    semantic_resolutions: list[dict] = []

    opened_odds = len(re.findall(r'(?m)^\s*ODD\s*\{', normalized))
    closed_odds = sum(1 for match in _BLOCK_RE.finditer(normalized) if match.group(1) == "ODD")
    if opened_odds != closed_odds:
        errors.append(f"TRUNCATED_ODD_BLOCK:OPENED={opened_odds}:CLOSED={closed_odds}")

    source_odd_count = 0

    def quarantine(source_index: int, block_type: str, fields: dict[str, str], reasons: list[str]) -> None:
        unique_reasons = sorted(set(reasons))
        quarantined_rows.append({
            "source_index": source_index,
            "source_record_id": f"{block_type}:{source_index}",
            "block_type": block_type,
            "category": fields.get("CATEGORY", ""),
            "family": fields.get("FAMILY", ""),
            "market": fields.get("MARKET", ""),
            "period": fields.get("PERIOD", ""),
            "owner": fields.get("OWNER", ""),
            "selection": fields.get("SELECTION", ""),
            "line": fields.get("LINE", ""),
            "odds": fields.get("ODDS", ""),
            "raw": fields.get("RAW", fields.get("RAW_ORIGINAL", "")),
            "reason": unique_reasons[0] if len(unique_reasons) == 1 else ";".join(unique_reasons),
            "reasons": unique_reasons,
            "stage": "PACKET_PARSER_SEMANTIC_VALIDATION" if block_type == "ODD" else "UPSTREAM_EXCLUSION_AUDIT",
            "original_fields": dict(fields),
        })

    match_value = header.get("MATCH", "")
    teams = [part.strip() for part in match_value.split(" - ", 1)] if " - " in match_value else []

    for source_index, match in enumerate(_BLOCK_RE.finditer(normalized), 1):
        name, body = match.group(1), match.group(2)
        fields = _parse_assignments(body)
        if name == "EQUIVALENCE_GROUP":
            item: dict = dict(fields)
            copies_match = re.search(r'(?ms)^\s*COPIES\s*=\s*(\[.*\])\s*;\s*$', body)
            if copies_match:
                try:
                    item["COPIES"] = json.loads(copies_match.group(1))
                except json.JSONDecodeError:
                    errors.append(f"EQUIVALENCE_COPIES_JSON_INVALID:{source_index}")
            equivalence_groups.append(item)
            continue

        if name != "ODD":
            quarantine(source_index, name, fields, [f"EXTRACTOR_{name}:{fields.get('REASON', 'UNSPECIFIED')}"])
            continue

        source_odd_count += 1

        family = fields.get("FAMILY", "").strip().upper()
        required_keys = list(_REQUIRED_ODD_KEYS)
        missing = [key for key in required_keys if key not in fields]
        if missing:
            quarantine(source_index, name, fields, [f"MISSING_CRITICAL_FIELDS:{','.join(missing)}"])
            continue
        empty_required = [key for key in ("CATEGORY", "FAMILY", "MARKET", "PERIOD", "SELECTION") if not fields[key].strip()]
        if empty_required:
            quarantine(source_index, name, fields, [f"EMPTY_CRITICAL_FIELDS:{','.join(empty_required)}"])
            continue
        period = fields["PERIOD"].strip().upper()
        if period not in _VALID_PERIODS:
            quarantine(source_index, name, fields, [f"UNSUPPORTED_PERIOD:{period or 'EMPTY'}"])
            continue
        if period == "MATCH_INCLUDING_EXTRA_TIME":
            from parser import classify_period_detail
            proven_period, _, _ = classify_period_detail(fields.get("MARKET", ""), "", family=family)
            if proven_period != period:
                quarantine(source_index, name, fields, ["UNPROVEN_STATISTICS_EXTRA_TIME_CONTRACT"])
                continue
        try:
            odds_value = _decimal(fields["ODDS"], "ODDS")
            line = _normal_line(fields["LINE"])
        except ValueError as exc:
            quarantine(source_index, name, fields, [f"INVALID_NUMBER:{exc}"])
            continue
        if odds_value <= 1.0:
            quarantine(source_index, name, fields, [f"ODDS_NOT_ABOVE_ONE:{odds_value:g}"])
            continue

        family = fields["FAMILY"].strip().upper()
        owner = fields["OWNER"].strip()
        if family.startswith("TEAM_TOTALS_") and not owner:
            quarantine(source_index, name, fields, ["TEAM_TOTAL_OWNER_MISSING"])
            continue
        if len(teams) == 2 and family == "TEAM_TOTALS_HOME" and owner != teams[0]:
            quarantine(source_index, name, fields, ["TEAM_TOTAL_OWNER_CONFLICT_HOME"])
            continue
        if len(teams) == 2 and family == "TEAM_TOTALS_AWAY" and owner != teams[1]:
            quarantine(source_index, name, fields, ["TEAM_TOTAL_OWNER_CONFLICT_AWAY"])
            continue
        if family in {"GOALS_OU", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY", "HANDICAP_EUROPEAN", "HANDICAP_ASIAN"} and not line:
            quarantine(source_index, name, fields, [f"LINE_REQUIRED:{family}"])
            continue

        resolved, audits, resolution_reasons = resolve_semantics(fields)
        if family.startswith("HANDICAP_") and (not resolved.get("HANDICAP_KIND") or not resolved.get("HANDICAP_TAXONOMY")):
            resolution_reasons.append("HANDICAP_KIND_OR_TAXONOMY_UNRESOLVED")
        if not resolved.get("SETTLEMENT", "").strip():
            resolution_reasons.append("SETTLEMENT_UNRESOLVED")
        if resolution_reasons:
            quarantine(source_index, name, fields, resolution_reasons)
            continue
        for audit in audits:
            semantic_resolutions.append({"source_index": source_index, **audit})
        fields = resolved

        home, away = teams if len(teams) == 2 else ("", "")
        canonical_outcome = fields["SELECTION"].strip().upper()
        if family == "DOUBLE_CHANCE":
            simple_market = not any(marker in _norm_words(fields["MARKET"]) for marker in ("&", "powyżej", "poniżej", "obie drużyny"))
            explicit_dc = fields["SELECTION"].strip().upper()
            explicit_dc = {"HOME_OR_DRAW": "1X", "HOME_OR_AWAY": "12", "DRAW_OR_AWAY": "X2", "1X": "1X", "12": "12", "X2": "X2"}.get(explicit_dc, "")
            canonical_outcome = (explicit_dc or _double_chance_outcome(fields.get("RAW", ""), home, away)) if simple_market else _compound_outcome(family, fields["MARKET"], fields.get("RAW", ""), home, away)
            if not canonical_outcome:
                quarantine(source_index, name, fields, ["AMBIGUOUS_COMPOUND_OUTCOME"])
                continue
        elif family == "FIRST_GOAL_TEAM" and ("wynik i kto" in _norm_words(fields["MARKET"]) or "result and" in _norm_words(fields["MARKET"])):
            canonical_outcome = _compound_outcome(family, fields["MARKET"], fields.get("RAW", ""), home, away)
            if not canonical_outcome:
                quarantine(source_index, name, fields, ["AMBIGUOUS_COMPOUND_OUTCOME"])
                continue
        elif family not in {"GOALSCORER", "PLAYER_COMBINATION"}:
            canonical_outcome = fields["SELECTION"].strip().upper()

        odds.append(OddRecord(
            category=fields["CATEGORY"].strip(), family=family, market=fields["MARKET"].strip(),
            period=period, owner=owner, selection=fields["SELECTION"].strip().upper(), line=line,
            handicap_kind=fields.get("HANDICAP_KIND", "").strip().upper(),
            handicap_taxonomy=fields.get("HANDICAP_TAXONOMY", "").strip().upper(),
            settlement=fields["SETTLEMENT"].strip().upper(), odds=odds_value,
            raw=fields.get("RAW", "").strip(), period_source=fields.get("PERIOD_SOURCE", "").strip(),
            period_confidence=fields.get("PERIOD_CONFIDENCE", "").strip().upper(),
            scorer_scope=fields.get("SCORER_SCOPE", "").strip().upper(), source_index=source_index,
            canonical_outcome=canonical_outcome,
            market_instance=fields.get("MARKET_INSTANCE_ID", "").strip(),
            participant=fields.get("PARTICIPANT", "").strip(),
            source_raw_record_ids=_source_record_ids(fields.get("SOURCE_RAW_RECORD_IDS", "")),
            event_teams=tuple(teams),
            selection_text=fields["SELECTION"].strip(),
            participants=tuple(p.strip() for p in fields.get("PARTICIPANTS", "").split(" + ") if p.strip()),
        ))

    if not odds:
        errors.append("NO_VALID_ODD_RECORDS")
    return ParsedPacket(
        header=header, odds=odds, equivalence_groups_raw=equivalence_groups,
        warnings=sorted(set(warnings)), errors=_collapse_record_errors(errors),
        normalized_text_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        source_odd_count=source_odd_count, quarantined_rows=quarantined_rows,
        semantic_resolutions=semantic_resolutions,
    )


def parse_packet_file(path: str | Path) -> ParsedPacket:
    return parse_packet_text(Path(path).read_text(encoding="utf-8-sig"))
