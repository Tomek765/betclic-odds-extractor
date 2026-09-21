"""Event-scoped native contestant short names; no fuzzy name inference."""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path


def extract_native_team_names(html: str, home: str, away: str, event_id: str = "") -> dict:
    class State(HTMLParser):
        def __init__(self):
            super().__init__(); self.active = False; self.parts = []
        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.active = dict(attrs).get("id") == "ng-state"
        def handle_endtag(self, tag):
            if tag == "script": self.active = False
        def handle_data(self, data):
            if self.active: self.parts.append(data)

    state = State(); state.feed(html)
    try:
        value = json.loads("".join(state.parts))
    except (ValueError, TypeError):
        return {}
    candidates = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and item[:1] in {"{", "["}:
            try: pending.append(json.loads(item))
            except ValueError: pass
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            contestants = item.get("contestants")
            native_id = str(item.get("matchId") or "")
            if (native_id and (not event_id or native_id == str(event_id))
                    and isinstance(contestants, list) and len(contestants) == 2
                    and all(isinstance(c, dict) for c in contestants)
                    and [c.get("name") for c in contestants] == [home, away]):
                short = tuple(str(c.get("shortName") or c["name"]) for c in contestants)
                candidates.add((native_id, *short))
            pending.extend(item.values())
    if len(candidates) != 1:
        return {}
    native_id, home_short, away_short = candidates.pop()
    return {"schema": "NATIVE_EVENT_TEAM_NAMES_V1", "event_id": native_id,
            "home": home, "away": away, "home_short": home_short, "away_short": away_short,
            "snapshot_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest()}


def saved_native_team_names(raw_path: Path, home: str, away: str) -> dict:
    """Read only snapshots named for this exact capture, without editing RAW."""
    match = re.fullmatch(r"raw_before_dedupe_(run_\d+_\d+)\.jsonl", raw_path.name)
    if not match:
        return {}
    snapshots = raw_path.parent.parent / "snapshots"
    # The result tab contains the native match metadata and Half/Full rows.
    paths = sorted(p for p in snapshots.glob(f"tab_{match.group(1)}_*_Wynik.html")
                   if re.fullmatch(rf"tab_{re.escape(match.group(1))}_\d+_Wynik\.html", p.name))
    if len(paths) != 1:
        return {}
    try:
        evidence = extract_native_team_names(paths[0].read_text(encoding="utf-8"), home, away)
    except (OSError, UnicodeError):
        return {}
    if evidence:
        evidence["snapshot_path"] = str(paths[0])
        evidence["capture_run_id"] = match.group(1)
    return evidence
