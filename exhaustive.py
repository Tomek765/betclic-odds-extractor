"""Stateful, non-betting UI crawler for exhaustive Betclic DOM capture."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MORE_RE = re.compile(r"(?:show|poka.{0,3}|rozwi.{0,3}|more|wi.{0,3})", re.IGNORECASE)


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

    def as_dict(self) -> dict[str, Any]:
        return {"main_tab": self.main_tab, "discovered_interactions": len(self.discovered_interactions),
                "visited_interactions": len(self.visited_interactions), "expanded_controls": self.expanded_controls,
                "remaining_closed": self.remaining_closed, "remaining_more": self.remaining_more,
                "scroll_containers": len(self.scroll_containers),
                "finished_scroll_containers": len(self.finished_scroll_containers),
                "unique_visible_signatures": len(self.unique_visible_signatures),
                "raw_exported_signatures": len(self.raw_exported_signatures),
                "virtualized_records_union_count": self.virtualized_records_union_count,
                "stabilization_passes": self.stabilization_passes}


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
          const controls=[];document.querySelectorAll('button,[role=tab],[aria-expanded],[aria-controls],[data-testid]').forEach((e,i)=>{const t=text(e),x=e.getAttribute('aria-expanded');if(!t||isOdd(e)||e.disabled)return;if(e.getAttribute('role')==='tab'||x==='false'||/show|more|poka.{0,3}|rozwi.{0,3}|wi.{0,3}/i.test(t))controls.push({index:i,role:e.getAttribute('role')||'',text:t,aria_controls:e.getAttribute('aria-controls')||'',expanded:x,semantic_path:path(e),local_index:Array.prototype.indexOf.call(e.parentElement.children,e)});});
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
    def _scroll(self, index: int, axis: str, position: int) -> bool:
        try: return bool(self.page.evaluate("""a=>{const e=Array.from(document.querySelectorAll('*'))[a.i];if(!e)return false;if(a.axis==='y')e.scrollTop=a.p;else e.scrollLeft=a.p;return true;}""", {"i": index, "axis": axis, "p": position}))
        except Exception: return False

    def crawl_tab(self, tab_name: str) -> tuple[list[dict[str, Any]], CoverageManifest]:
        manifest, union, stable_passes, capture_no = CoverageManifest(tab_name), {}, 0, 0
        while time.time() < self.deadline and stable_passes < 3:
            before, capture_no = len(union), capture_no + 1
            for raw_record in self.capture(self.page, tab_name):
                record = dict(raw_record); record.setdefault("capture_id", f"{tab_name}:{capture_no}")
                record.setdefault("main_tab", tab_name); record.setdefault("subtab", "")
                record.setdefault("market_group", record.get("market", "")); record.setdefault("ancestor_title", record.get("market", ""))
                record.setdefault("interaction_state_key", tab_name); record.setdefault("scroll_container_key", "page"); record.setdefault("scroll_position", "")
                sig = raw_signature(record)
                if sig: union.setdefault(sig, record); manifest.unique_visible_signatures.add(sig)
            snap, actionable = self._snapshot(), []
            for control in snap.get("controls", []):
                key = stable_interaction_key(control, tab_name); manifest.discovered_interactions.add(key)
                if key not in manifest.visited_interactions and (control.get("expanded") == "false" or MORE_RE.search(control.get("text", "")) or control.get("role") == "tab"): actionable.append((key, control))
            if actionable:
                key, control = actionable[0]
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
            stable_passes = stable_passes + 1 if len(union) == before else 0
        final = self._snapshot(); reconcile_active_scroll_containers(manifest, final); manifest.remaining_closed = sum(c.get("expanded") == "false" for c in final.get("controls", [])); manifest.remaining_more = sum(bool(MORE_RE.search(c.get("text", ""))) for c in final.get("controls", [])); manifest.stabilization_passes = stable_passes; manifest.raw_exported_signatures = set(union); manifest.virtualized_records_union_count = len(union)
        return list(union.values()), manifest
