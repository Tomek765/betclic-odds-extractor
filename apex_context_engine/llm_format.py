"""Clean, token-lean odds text for pasting into an LLM.

This is the only serializer for user/LLM-facing output.  It carries what
identifies a bet (market, selection, line, period, owner, settlement, odds)
and nothing about how the scraper found it: lineage ids, DOM paths, runtime,
build and audit data stay in the internal machine packet and diagnostics.

Format (deterministic):

    MATCH=Home - Away
    COMPETITION=...
    KICKOFF=20:45
    ODDS_COUNT=N
    ODDS
    FAMILY|MARKET|PERIOD|OWNER|SELECTION|LINE|ODDS|SETTLEMENT
    1X2|Wynik meczu|FULL_TIME|Home|HOME||2.27|WIN_LOSE
    GOALSCORER|Strzelec|FULL_TIME|Away|Player||2.20|WIN_LOSE|PARTICIPANT=Player|SCORER_SCOPE=ANYTIME

Optional fields are appended as KEY=value only on rows that carry them;
PARTICIPANTS lists the named players of a combination joined by " + ".
A literal "|" or "\\" inside a value is backslash-escaped.  Rows whose
complete emitted record and source text are identical (the same offer shown in
several tabs) are written once; otherwise each keeps a RAW=... disambiguator.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

HEADER_FIELDS = ("MATCH", "COMPETITION", "KICKOFF")
COLUMNS = ("FAMILY", "MARKET", "PERIOD", "OWNER", "SELECTION", "LINE", "ODDS", "SETTLEMENT")
OPTIONAL_FIELDS = ("HANDICAP_KIND", "HANDICAP_TAXONOMY", "PARTICIPANT", "PARTICIPANTS", "SCORER_SCOPE")
PARTICIPANTS_SEPARATOR = " + "


def _clean(value: Any) -> str:
    text = " ".join(str("" if value is None else value).split())
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _odds_text(value: Any) -> str:
    # Keep the bookmaker's string exactly; a parsed float keeps its value.
    return repr(value) if isinstance(value, float) else str(value or "")


def _optional_value(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if key == "PARTICIPANTS":
        names = [" ".join(str(name).split()) for name in (value or []) if str(name).strip()]
        # A single participant already emitted as PARTICIPANT is not repeated.
        if names == [" ".join(str(record.get("PARTICIPANT") or "").split())]:
            return ""
        value = PARTICIPANTS_SEPARATOR.join(names)
    return _clean(value)


def odds_row(record: Mapping[str, Any]) -> str:
    """One bet as a single line. Keys are the packet's uppercase field names."""
    cells = [_clean(_odds_text(record.get(key)) if key == "ODDS" else record.get(key)) for key in COLUMNS]
    extras = [f"{key}={value}" for key in OPTIONAL_FIELDS if (value := _optional_value(record, key))]
    return "|".join(cells + extras)


def render_llm_odds(header: Mapping[str, Any], records: Iterable[Mapping[str, Any]],
                    status: str = "") -> str:
    rows: list[str] = []
    variants: dict[str, list[str]] = {}
    shown: dict[str, str] = {}
    for record in records:
        # The Top card and the Wynik tab can title one market "Podwójna Szansa"
        # and "Podwójna szansa": same bet, same price.  The identity ignores the
        # letter case and spacing of the title; the first spelling is shown.
        identity = odds_row({**record, "MARKET": " ".join(str(record.get("MARKET") or "").casefold().split())})
        raw = _clean(record.get("RAW"))
        if identity not in variants:
            variants[identity] = []
            shown[identity] = odds_row(record)
            rows.append(identity)
        if raw not in variants[identity]:
            variants[identity].append(raw)
    variants = {shown[key]: value for key, value in variants.items()}
    rows = [shown[key] for key in rows]
    # Identical rows from the same displayed offer (e.g. the Top and Wynik copy
    # of one market) are written once.  If the source texts differ, the
    # structured fields did not capture everything, so each offer keeps its
    # own RAW text instead of being merged.
    rows = [expanded for row in rows for expanded in (
        [row] if len(variants[row]) < 2 else [f"{row}|RAW={raw}" for raw in variants[row]])]
    lines = [f"{key}={' '.join(str(header.get(key) or '').split())}" for key in HEADER_FIELDS]
    if status:
        lines.append(f"DATA_STATUS={status}")
    lines += [f"ODDS_COUNT={len(rows)}", "ODDS", "|".join(COLUMNS), *rows]
    return "\n".join(lines) + "\n"


def parse_llm_row(line: str) -> dict[str, str]:
    """Inverse of odds_row, used to prove the clean output is lossless."""
    cells, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
    cells.append("".join(current))
    record = dict(zip(COLUMNS, cells[:len(COLUMNS)]))
    for extra in cells[len(COLUMNS):]:
        key, _, value = extra.partition("=")
        record[key] = value
    return record
