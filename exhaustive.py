"""Stateful, non-betting UI crawler for exhaustive Betclic DOM capture."""
from __future__ import annotations

import os
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

EMPTY_TAB_GRACE_SECONDS = 8.0
# A tab is complete only after no NEW selection appeared for this long: rows
# rendered lazily, or revealed by an expander or a scroll, arrive late.  Three
# quick identical passes (~0.3 s) could end a tab before they did.
QUIET_SECONDS = 1.2
MORE_RE = re.compile(r"(?:show|poka.{0,3}|rozwi.{0,3}|more|wi.{0,3})", re.IGNORECASE)

# Player-specific markets (scorer lists, assist lists, pairs/triples of players)
# expand into their whole long tail: a live audit (Niemcy - Serbia, 2026-09-29)
# went from ~1,100 to 4,723 accepted bets, 4,160 of them player combinations,
# with a 654 KB package and tabs that no longer finished within their time box.
# Only the shortest-priced entries Betclic shows by default matter for a
# pre-match read, so these markets keep their default view.  The skip is
# recorded in the coverage manifest (see_more_skipped), never silent.
PLAYER_MARKET_RE = re.compile(
    r"zawodnik|gracz|strzelec|strzelcy|asyst|zmiennik|supersub|xtra|ktorykolwiek|obaj|wszyscy|jeden z")


def is_player_market_title(title: str) -> bool:
    folded = unicodedata.normalize("NFKD", str(title).replace("ł", "l").replace("Ł", "L"))
    folded = " ".join(folded.encode("ascii", "ignore").decode().casefold().split())
    return bool(PLAYER_MARKET_RE.search(folded))


def expand_player_markets() -> bool:
    return os.environ.get("APEX_EXPAND_PLAYER_MARKETS", "") == "1"


@dataclass
class CoverageManifest:
    main_tab: str
    discovered_interactions: set[str] = field(default_factory=set)
    visited_interactions: set[str] = field(default_factory=set)
    expanded_controls: int = 0
    remaining_closed: int = 0
    remaining_more: int = 0
    scroll_containers: set[str] = field(default_factory=set)
    finished_scroll_containers: set[str] = field(default_factory=set)
    unique_visible_signatures: set[str] = field(default_factory=set)
    raw_exported_signatures: set[str] = field(default_factory=set)
    virtualized_records_union_count: int = 0
    stabilization_passes: int = 0
    see_more_baseline: dict[str, int] = field(default_factory=dict)
    see_more_skipped: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {"main_tab": self.main_tab, "discovered_interactions": len(self.discovered_interactions),
                "visited_interactions": len(self.visited_interactions), "expanded_controls": self.expanded_controls,
                "remaining_closed": self.remaining_closed, "remaining_more": self.remaining_more,
                "scroll_containers": len(self.scroll_containers),
                "finished_scroll_containers": len(self.finished_scroll_containers),
                "unique_visible_signatures": len(self.unique_visible_signatures),
                "raw_exported_signatures": len(self.raw_exported_signatures),
                "virtualized_records_union_count": self.virtualized_records_union_count,
                "stabilization_passes": self.stabilization_passes,
                "see_more_skipped": len(self.see_more_skipped)}


def stable_interaction_key(item: dict[str, Any], main_tab: str) -> str:
    keys = ("role", "text", "aria_controls", "semantic_path", "local_index")
    return "|".join([main_tab.lower(), *(str(item.get(k, "")).strip().lower() for k in keys)])


def raw_signature(item: dict[str, Any]) -> str:
    """Return the union identity for one visible priced control.

    A Betclic native selection id is the only evidence that two separately
    rendered controls are clones of the same selection.  In its absence the
    market instance (which contains the sibling market, column and cell path)
    must remain part of the identity: the same player/price can be offered in
    two distinct scorer markets.
    """
    native_id = item.get("native_selection_id") or item.get("selection_id")
    if native_id:
        return "native:" + str(native_id).strip().lower()
    keys = (
        "market_instance_id", "market", "selection", "participant_hint", "odds", "section_title",
        "ancestor_title", "heading_path", "column_heading", "line_hint", "period_hint",
    )
    return "|".join(str(item.get(k, "")).strip().lower() for k in keys)


def selection_identity(item: dict[str, Any]) -> str:
    """raw_signature without the price: a price tick is not a new selection."""
    native_id = item.get("native_selection_id") or item.get("selection_id")
    if native_id:
        return "native:" + str(native_id).strip().lower()
    keys = (
        "market_instance_id", "market", "selection", "participant_hint", "section_title",
        "ancestor_title", "heading_path", "column_heading", "line_hint", "period_hint",
    )
    return "|".join(str(item.get(k, "")).strip().lower() for k in keys)


def reconcile_active_scroll_containers(manifest: CoverageManifest, snapshot: dict[str, Any]) -> int:
    """Keep only currently active material containers and mark those at both ends."""
    active = {str(box["key"]) for box in snapshot.get("scrolls", [])}
    manifest.scroll_containers.intersection_update(active)
    manifest.finished_scroll_containers.intersection_update(active)
    for box in snapshot.get("scrolls", []):
        key = str(box["key"])
        manifest.scroll_containers.add(key)
        y_done = int(box["height"]) <= int(box["client"]) + 2 or int(box["top"]) >= int(box["height"]) - int(box["client"]) - 1
        x_done = int(box["width"]) <= int(box["clientWidth"]) + 2 or int(box["left"]) >= int(box["width"]) - int(box["clientWidth"]) - 1
        if y_done and x_done:
            manifest.finished_scroll_containers.add(key)
    return len(manifest.scroll_containers - manifest.finished_scroll_containers)


class ExhaustiveStateCrawler:
    """Crawls controls and nested scroll areas without clicking price buttons."""
    def __init__(self, page: Any, capture: Callable[[Any, str], list[dict[str, Any]]],
                 deadline: float, log: Callable[[str], None] | None = None) -> None:
        self.page, self.capture, self.deadline = page, capture, deadline
        self.log = log or (lambda _: None)

    @staticmethod
    def _script() -> str:
        return """() => { const text=e=>(e.innerText||e.textContent||'').replace(/\\s+/g,' ').trim();
          const path=e=>{const a=[];for(let n=e;n&&n!==document.body;n=n.parentElement){if(n.matches('.marketBox,sports-market,[role=tabpanel],.accordion'))a.push(text(n).slice(0,80));}return a.join('>');};
          const isOdd=e=>e.matches('button')&&(/\\bodd\\b/i.test(e.className||'')||/^\\s*\\d{1,3}[,.]\\d{2}\\s*$/.test(text(e)));
          const controls=[],seeCount={};document.querySelectorAll('button,[role=tab],[aria-expanded],[aria-controls],[data-testid]').forEach((e,i)=>{const t=text(e),x=e.getAttribute('aria-expanded');
          if(!isOdd(e)&&!e.disabled&&/seeMore/i.test(e.className||'')&&!e.closest('sports-betting-slip')){const box=e.closest('sports-markets-single-market,sports-market,.marketBox'),head=box&&box.querySelector('.marketBox_headTitle,h2,h3'),title=head?text(head):'',icon=e.querySelector('[class*=icon_arrow]'),k=title.toLowerCase();seeCount[k]=(seeCount[k]||0)+1;controls.push({index:i,role:'',text:'expander',aria_controls:'',expanded:/arrowUp/i.test(icon?String(icon.className||''):'')?'true':'false',semantic_path:title+'#'+seeCount[k],local_index:0,see_more:true,odds_in_box:box?Array.from(box.querySelectorAll('button')).filter(isOdd).length:0});return;}
          if(!t||isOdd(e)||e.disabled)return;if(e.getAttribute('role')==='tab'||x==='false'||/show|more|poka.{0,3}|rozwi.{0,3}|wi.{0,3}/i.test(t))controls.push({index:i,role:e.getAttribute('role')||'',text:t,aria_controls:e.getAttribute('aria-controls')||'',expanded:x,semantic_path:path(e),local_index:Array.prototype.indexOf.call(e.parentElement.children,e)});});
          const scrolls=[];document.querySelectorAll('*').forEach((e,i)=>{const s=getComputedStyle(e),panel=e.closest('[role=tabpanel]');const active=e.isConnected&&e.getClientRects().length>0&&s.display!=='none'&&s.visibility!=='hidden'&&e.getAttribute('aria-hidden')!=='true'&&!(panel&&(panel.hidden||panel.getAttribute('aria-hidden')==='true'));const material=active&&Array.from(e.querySelectorAll('button,[role=button]')).some(isOdd);if(material&&((e.scrollHeight>e.clientHeight+2&&/(auto|scroll)/.test(s.overflowY))||(e.scrollWidth>e.clientWidth+2&&/(auto|scroll)/.test(s.overflowX))))scrolls.push({index:i,key:(e.id||e.className||e.tagName)+'|'+i,top:e.scrollTop,height:e.scrollHeight,client:e.clientHeight,left:e.scrollLeft,width:e.scrollWidth,clientWidth:e.clientWidth});});return {controls,scrolls}; }"""

    def _snapshot(self) -> dict[str, Any]:
        try:
            snapshot = self.page.evaluate(self._script())
            return snapshot if isinstance(snapshot, dict) else {"controls": [], "scrolls": []}
        except Exception:
            return {"controls": [], "scrolls": []}
    def _click_control(self, index: int) -> bool:
        try: return bool(self.page.evaluate("""i=>{const e=Array.from(document.querySelectorAll('button,[role=tab],[aria-expanded],[aria-controls],[data-testid]'))[i];if(!e)return false;e.click();return true;}""", index))
        except Exception: return False
    def _click_controls(self, indices: list[int]) -> int:
        """Click several controls resolved to elements *before* the first click.

        Opening a market inserts price buttons, which shifts the position of
        every later control; resolving all references up front keeps each click
        on the intended element.
        """
        try: return int(self.page.evaluate("""idx=>{const all=Array.from(document.querySelectorAll('button,[role=tab],[aria-expanded],[aria-controls],[data-testid]'));const els=idx.map(i=>all[i]);let n=0;for(const e of els){if(e){e.click();n++;}}return n;}""", indices))
        except Exception: return 0
    def _scroll(self, index: int, axis: str, position: int) -> bool:
        try: return bool(self.page.evaluate("""a=>{const e=Array.from(document.querySelectorAll('*'))[a.i];if(!e)return false;if(a.axis==='y')e.scrollTop=a.p;else e.scrollLeft=a.p;return true;}""", {"i": index, "axis": axis, "p": position}))
        except Exception: return False

    @staticmethod
    def _see_more_resolved(control: dict[str, Any], tab_name: str, manifest: CoverageManifest) -> bool:
        """A clicked icon expander whose market now shows more priced buttons is open.

        Betclic flips the arrow when it opens; if that ever changes, the growth
        of the market is the evidence.  An expander that was never used, or
        that revealed nothing, is reported as still closed (fail closed).
        """
        if not control.get("see_more"):
            return False
        key = stable_interaction_key(control, tab_name)
        if key in manifest.see_more_skipped:
            return True
        return (key in manifest.visited_interactions
                and int(control.get("odds_in_box") or 0) > manifest.see_more_baseline.get(key, 1 << 30))

    def crawl_tab(self, tab_name: str) -> tuple[list[dict[str, Any]], CoverageManifest]:
        manifest, union, stable_passes, capture_no = CoverageManifest(tab_name), {}, 0, 0
        identities: set[str] = set()
        # Betclic renders some tabs lazily: three quick empty passes ended the
        # Strzelcy tab after 0.8 s with zero rows (live 2026-10-01, Bosnia and
        # Herzegovina - Sweden).  An empty market tab must wait for content.
        started, wait_for_content = time.time(), tab_name.strip().casefold() != "mycombi"
        last_growth = started
        while time.time() < self.deadline and stable_passes < 3:
            before, capture_no = len(identities), capture_no + 1
            for raw_record in self.capture(self.page, tab_name):
                record = dict(raw_record); record.setdefault("capture_id", f"{tab_name}:{capture_no}")
                record.setdefault("main_tab", tab_name); record.setdefault("subtab", "")
                record.setdefault("market_group", record.get("market", "")); record.setdefault("ancestor_title", record.get("market", ""))
                record.setdefault("interaction_state_key", tab_name); record.setdefault("scroll_container_key", "page"); record.setdefault("scroll_position", "")
                sig = raw_signature(record)
                if sig:
                    previous = union.get(sig)
                    # The same native selection re-read at a new price keeps
                    # the latest price (other signatures already carry the price).
                    if previous is None or str(previous.get("odds", "")) != str(record.get("odds", "")):
                        union[sig] = record
                    manifest.unique_visible_signatures.add(sig)
                    identities.add(selection_identity(record))
            snap, actionable = self._snapshot(), []
            for control in snap.get("controls", []):
                key = stable_interaction_key(control, tab_name); manifest.discovered_interactions.add(key)
                if control.get("see_more"):
                    manifest.see_more_baseline.setdefault(key, int(control.get("odds_in_box") or 0))
                    if not expand_player_markets() and is_player_market_title(str(control.get("semantic_path", "")).rsplit("#", 1)[0]):
                        manifest.see_more_skipped.add(key); continue
                if key not in manifest.visited_interactions and (control.get("expanded") == "false" or MORE_RE.search(control.get("text", "")) or control.get("role") == "tab"): actionable.append((key, control))
            if actionable:
                key, control = actionable[0]
                if control.get("see_more"):
                    batch = [(k, c) for k, c in actionable if c.get("see_more")]
                    if len(batch) > 1 and self._click_controls([int(c["index"]) for _, c in batch]) == len(batch):
                        manifest.visited_interactions.update(k for k, _ in batch); manifest.expanded_controls += len(batch)
                        time.sleep(.15); stable_passes = 0; continue
                if self._click_control(int(control["index"])): manifest.visited_interactions.add(key); manifest.expanded_controls += 1; time.sleep(.12); stable_passes = 0; continue
            scrolled = False
            for box in snap.get("scrolls", []):
                key = str(box["key"]); manifest.scroll_containers.add(key)
                for axis, size, client, pos in (("y", box["height"], box["client"], box["top"]), ("x", box["width"], box["clientWidth"], box["left"])):
                    if size > client + 2 and pos < size - client - 1:
                        self._scroll(int(box["index"]), axis, min(pos + max(120, client // 2), size - client)); time.sleep(.08); scrolled = True; break
                if scrolled: break
                manifest.finished_scroll_containers.add(key)
            if scrolled: stable_passes = 0; continue
            if not union and wait_for_content and time.time() - started < EMPTY_TAB_GRACE_SECONDS:
                stable_passes = 0; time.sleep(.4); continue
            if len(identities) != before:
                last_growth, stable_passes = time.time(), 0
            else:
                stable_passes += 1
                if stable_passes >= 3 and time.time() - last_growth < QUIET_SECONDS:
                    stable_passes = 2; time.sleep(.2)
        final = self._snapshot(); reconcile_active_scroll_containers(manifest, final); manifest.remaining_closed = sum(c.get("expanded") == "false" and not self._see_more_resolved(c, tab_name, manifest) for c in final.get("controls", [])); manifest.remaining_more = sum(bool(MORE_RE.search(c.get("text", ""))) for c in final.get("controls", []) if not c.get("see_more")); manifest.stabilization_passes = stable_passes; manifest.raw_exported_signatures = set(union); manifest.virtualized_records_union_count = len(union)
        return list(union.values()), manifest
