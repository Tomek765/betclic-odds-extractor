from __future__ import annotations

import os
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from context_engine_adapter import ContextRunResult, packet_is_ready, run_context_engine
from core import BUILD_ID, BetclicOddsExtractor, _evaluate_clean_core_gate
from diagnostics import BASE_DIR, DiagnosticsManager


def _partial_result_details(result: dict[str, Any]) -> dict[str, Any]:
    """Build a transparent UI summary for a completed, gated partial capture."""
    unknown_count = sum(item.get("PERIOD") == "UNKNOWN" for item in result.get("odds", []))
    unresolved_count = int(result.get("unresolved_count", len(result.get("unresolved", []))) or 0)
    reasons = result.get("incomplete_reasons") or [result.get("parser_truth_status", "PARTIAL")]
    return {
        "odds_count": int(result.get("odds_count", 0) or 0),
        "unknown_count": unknown_count,
        "unresolved_count": unresolved_count,
        "reason": ", ".join(str(reason) for reason in reasons if reason),
        "packet_text": result.get("packet_text", ""),
        "llm_packet_text": result.get("llm_packet_text", ""),
    }


def _is_completed_gated_capture(result: dict[str, Any]) -> bool:
    """Separate a completed quality-gated result from a transport/runtime error."""
    return bool(
        result.get("status") not in ("GOTOWE", "PARTIAL")
        and not result.get("error")
        and int(result.get("odds_count", 0) or 0) > 0
        and result.get("packet_text")
        and result.get("incomplete_reasons")
        and result.get("analysis_ready") == "NO"
    )


def _gated_result_details(result: dict[str, Any]) -> dict[str, Any]:
    """Expose the retained quality blockers without altering either readiness gate."""
    details = _partial_result_details(result)
    gate = _evaluate_clean_core_gate(result.get("odds", []), result.get("unresolved", []), [])
    details.update({
        "core_blockers": gate["core_unknown_count"] + gate["core_unresolved_count"],
        "analysis_scope": result.get("analysis_scope") or gate["analysis_scope"],
    })
    return details


class BetclicExtractorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"APEX CONTEXT ENGINE  [{BUILD_ID}]")
        self.root.geometry("960x720")
        self.root.minsize(800, 600)

        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.bg_color     = "#1e1e2e"
        self.card_bg      = "#282a36"
        self.fg_color     = "#f8f8f2"
        self.accent_red   = "#ff5555"
        self.accent_green = "#50fa7b"
        self.accent_blue  = "#8be9fd"
        self.accent_orange = "#ffb86c"

        self.root.configure(bg=self.bg_color)
        self._configure_styles()

        self._build_header()
        self._build_input_section()
        self._build_status_and_counters()
        self._build_preview_section()
        self._build_bottom_bar()

        self.is_running = False
        self.context_is_running = False
        self.current_packet = ""

    # ------------------------------------------------------------------ styles

    def _configure_styles(self) -> None:
        self.style.configure(".", background=self.bg_color, foreground=self.fg_color,
                             font=("Segoe UI", 10))
        self.style.configure("TFrame", background=self.bg_color)
        self.style.configure("Card.TFrame", background=self.card_bg, relief="flat", borderwidth=1)

        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"),
                             foreground=self.accent_red, background=self.bg_color)
        self.style.configure("BuildID.TLabel", font=("Segoe UI", 8),
                             foreground="#6272a4", background=self.bg_color)
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 9),
                             foreground="#8b92a5", background=self.bg_color)

        self.style.configure("Status.TLabel", font=("Segoe UI", 11, "bold"),
                             background=self.card_bg)
        self.style.configure("CounterTitle.TLabel", font=("Segoe UI", 8, "bold"),
                             foreground="#8b92a5", background=self.card_bg)
        self.style.configure("CounterValue.TLabel", font=("Segoe UI", 16, "bold"),
                             foreground=self.accent_blue, background=self.card_bg)

        self.style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"),
                             background="#d2161e", foreground="#ffffff")
        self.style.map("Primary.TButton",
                       background=[("active", "#b01218"), ("disabled", "#552024")])

        self.style.configure("Secondary.TButton", font=("Segoe UI", 9),
                             background="#44475a", foreground="#ffffff")
        self.style.map("Secondary.TButton", background=[("active", "#6272a4")])

        self.style.configure("Custom.Horizontal.TProgressbar", thickness=12,
                             troughcolor="#282a36", background="#ff5555")

    # ------------------------------------------------------------------ header

    def _build_header(self) -> None:
        hf = ttk.Frame(self.root, padding=(15, 10, 15, 2))
        hf.pack(fill="x")

        ttk.Label(hf, text="BETCLIC FULL ODDS EXTRACTOR", style="Header.TLabel").pack(anchor="w")
        ttk.Label(hf, text=f"BUILD: {BUILD_ID}", style="BuildID.TLabel").pack(anchor="w")
        ttk.Label(
            hf,
            text="Automatyczny ekstraktor pełnej oferty kursowej Betclic — jeden przycisk, pełny skan",
            style="SubHeader.TLabel"
        ).pack(anchor="w")

    # ------------------------------------------------------------------ input

    def _build_input_section(self) -> None:
        card = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        card.pack(fill="x", padx=15, pady=5)

        ttk.Label(card, text="WKLEJ LINK BETCLIC:", font=("Segoe UI", 10, "bold"),
                  background=self.card_bg, foreground=self.accent_blue).pack(anchor="w", pady=(0, 5))

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")

        self.url_entry = tk.Entry(
            row, font=("Segoe UI", 10), bg="#191a21", fg="#f8f8f2",
            insertbackground="#ffffff", relief="solid", bd=1
        )
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 10))
        self.url_entry.focus()
        self._add_paste_menu(self.url_entry)

        btn_bar = ttk.Frame(card, style="Card.TFrame")
        btn_bar.pack(fill="x", pady=(10, 0))

        self.btn_download = ttk.Button(
            btn_bar,
            text="▶  POBIERZ WSZYSTKIE KURSY",
            style="Primary.TButton",
            command=self.start_extraction
        )
        self.btn_download.pack(side="left", ipadx=18, ipady=5)

        self.btn_copy = ttk.Button(
            btn_bar,
            text="📋  KOPIUJ PAKIET",
            style="Secondary.TButton",
            command=self.copy_packet
        )
        self.btn_copy.pack(side="left", padx=(14, 0), ipadx=12, ipady=5)

        self.btn_context = ttk.Button(
            btn_bar,
            text="ZBUDUJ KONTEKST RYNKU",
            style="Secondary.TButton",
            command=self.start_context_build,
            state="disabled",
        )
        self.btn_context.pack(side="left", padx=(14, 0), ipadx=12, ipady=5)

        self.lbl_context_status = ttk.Label(
            btn_bar, text="CONTEXT: WAITING", font=("Segoe UI", 8),
            background=self.card_bg, foreground="#8b92a5",
        )
        self.lbl_context_status.pack(side="left", padx=(10, 0))

        ttk.Label(
            card,
            text="Przeglądarka uruchamia się automatycznie. Pierwsze uruchomienie — zaakceptuj cookies w otwartym oknie Chrome.",
            font=("Segoe UI", 8), background=self.card_bg, foreground="#8b92a5"
        ).pack(anchor="w", pady=(8, 0))

    def _add_paste_menu(self, widget: tk.Entry) -> None:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Wklej", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_command(label="Wyczyść", command=lambda: widget.delete(0, tk.END))
        widget.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))

    # ------------------------------------------------------------------ status

    def _build_status_and_counters(self) -> None:
        card = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        card.pack(fill="x", padx=15, pady=5)

        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 8))

        ttk.Label(top, text="STATUS: ", font=("Segoe UI", 10, "bold"),
                  background=self.card_bg, foreground="#8b92a5").pack(side="left")
        self.lbl_status = ttk.Label(top, text="GOTOWE", style="Status.TLabel",
                                    foreground=self.accent_green)
        self.lbl_status.pack(side="left")
        self.lbl_status_msg = ttk.Label(top, text="Oczekiwanie na link...",
                                        font=("Segoe UI", 9), background=self.card_bg,
                                        foreground="#8b92a5")
        self.lbl_status_msg.pack(side="left", padx=(15, 0))

        self.progress = ttk.Progressbar(card, style="Custom.Horizontal.TProgressbar",
                                        mode="determinate")
        self.progress.pack(fill="x", pady=(0, 10))

        cf = ttk.Frame(card, style="Card.TFrame")
        cf.pack(fill="x")

        self.val_groups    = self._counter(cf, "ZAKŁADKI RYNKU", "0", 0)
        self.val_markets   = self._counter(cf, "RYNKI", "0", 1)
        self.val_odds      = self._counter(cf, "SELEKCJE KURSOWE", "0", 2)
        self.val_unresolved = self._counter(cf, "NIEROZWIĄZANE", "0", 3, is_last=True)

    def _counter(self, parent: ttk.Frame, title: str, val: str, col: int,
                 is_last: bool = False) -> ttk.Label:
        box = ttk.Frame(parent, style="Card.TFrame", padding=6)
        box.pack(side="left", fill="x", expand=True,
                 padx=(0 if col == 0 else 5, 0 if is_last else 5))
        ttk.Label(box, text=title, style="CounterTitle.TLabel").pack(anchor="w")
        v = ttk.Label(box, text=val, style="CounterValue.TLabel")
        v.pack(anchor="w")
        return v

    # ------------------------------------------------------------------ preview

    def _build_preview_section(self) -> None:
        pf = ttk.Frame(self.root, padding=(15, 5, 15, 5))
        pf.pack(fill="both", expand=True)

        ttk.Label(pf, text="PODGLĄD PAKIETU KURSOWEGO:",
                  font=("Segoe UI", 9, "bold"), foreground="#8b92a5").pack(anchor="w", pady=(0, 2))

        tf = ttk.Frame(pf)
        tf.pack(fill="both", expand=True)

        self.txt_preview = tk.Text(
            tf, font=("Consolas", 9), bg="#191a21", fg="#f8f8f2",
            insertbackground="#ffffff", relief="solid", bd=1, wrap="none"
        )
        sy = ttk.Scrollbar(tf, orient="vertical", command=self.txt_preview.yview)
        sx = ttk.Scrollbar(tf, orient="horizontal", command=self.txt_preview.xview)
        self.txt_preview.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)

        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        self.txt_preview.pack(side="left", fill="both", expand=True)

    # ------------------------------------------------------------------ bottom

    def _build_bottom_bar(self) -> None:
        bf = ttk.Frame(self.root, padding=(15, 4, 15, 8))
        bf.pack(fill="x")
        ttk.Button(bf, text="OTWÓRZ FOLDER DIAGNOSTYKI", style="Secondary.TButton",
                   command=DiagnosticsManager.open_diagnostics_folder).pack(side="right")

    # ------------------------------------------------------------------ actions

    def start_extraction(self) -> None:
        if self.is_running:
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Brak URL", "Wklej poprawny link do meczu Betclic.")
            return

        self.is_running = True
        self.btn_download.config(state="disabled")
        self.lbl_status.config(text="PRACUJE", foreground=self.accent_orange)
        self.lbl_status_msg.config(text="Uruchamianie...")
        self.progress["value"] = 0
        self.val_groups.config(text="0")
        self.val_markets.config(text="0")
        self.val_odds.config(text="0")
        self.val_unresolved.config(text="0")
        self.current_packet = ""
        self.btn_context.config(state="disabled")
        self.lbl_context_status.config(text="CONTEXT: WAITING", foreground="#8b92a5")
        self.txt_preview.delete("1.0", tk.END)

        threading.Thread(target=self._worker, args=(url,), daemon=True).start()

    def _update_progress(self, percent: float, msg: str) -> None:
        self.root.after(0, lambda: (
            setattr(self.progress, "value", percent * 100) or
            self.progress.configure(value=percent * 100) or
            self.lbl_status_msg.config(text=msg[:80])
        ))

    def _worker(self, url: str) -> None:
        diag = DiagnosticsManager()
        diag.log("WORKER_STARTED")
        try:
            ext = BetclicOddsExtractor(progress_callback=self._update_progress, diag=diag)
            res = ext.extract(url)
            self.root.after(0, lambda: self._on_done(res))
        except BaseException as exc:
            diag.log(f"CRITICAL_WORKER_EXCEPTION: {exc}\n{traceback.format_exc()}")
            error_result = {
                "status": "BŁĄD",
                "error": f"Krytyczny błąd: {exc}",
                "packet_text": ""
            }
            self.root.after(0, lambda result=error_result: self._on_done(result))

    def _on_done(self, result: dict[str, Any]) -> None:
        self.is_running = False
        self.btn_download.config(state="normal")

        if result.get("status") == "GOTOWE":
            full_usable = result.get("full_usable_ready") == "YES"
            self.lbl_status.config(text="GOTOWE / FULL USABLE" if full_usable else "GOTOWE", foreground=self.accent_green)
            elapsed = result.get("execution_time_sec", 0)
            tabs = ",".join(result.get("scanned_tabs", []))
            if full_usable:
                full_usable_summary = (
                    f"FULL_USABLE_READY=YES | ANALYSIS_READY={result.get('analysis_ready', '')} | "
                    f"ANALYSIS_SCOPE={result.get('analysis_scope', '')} | "
                    f"SOURCE_INCOMPLETE_INSTANCES={len(result.get('source_incomplete_instances', []))} | "
                    f"EXCLUDED_ROWS={result.get('excluded_rows', 0)} | "
                    f"UNRESOLVED_COUNT={result.get('unresolved_count', 0)}"
                )
            else:
                full_usable_summary = ""
            self.lbl_status_msg.config(text=f"Pobrano w {elapsed}s | Zakładki: {tabs}")
            if full_usable_summary:
                self.lbl_status_msg.config(text=full_usable_summary[:180])
            self.progress["value"] = 100
            self.val_groups.config(text=str(result.get("market_group_count", 0)))
            self.val_markets.config(text=str(result.get("market_count", 0)))
            self.val_odds.config(text=str(result.get("odds_count", 0)))
            self.val_unresolved.config(text=str(result.get("unresolved_count", 0)))
            self._show_packet(result.get("packet_text", ""), result.get("llm_packet_text", ""))
            self.btn_copy.config(state="normal")
            self._refresh_context_button()
        elif result.get("status") == "PARTIAL":
            details = _partial_result_details(result)
            self.lbl_status.config(text="CZĘŚCIOWE", foreground=self.accent_orange)
            self.lbl_status_msg.config(
                text=(f"Pobrano {details['odds_count']} kursów | UNKNOWN: {details['unknown_count']} | "
                      f"nierozwiązane: {details['unresolved_count']} | ograniczenie: {details['reason']}")[:180]
            )
            self.progress["value"] = 100
            self.val_groups.config(text=str(result.get("market_group_count", 0)))
            self.val_markets.config(text=str(result.get("market_count", 0)))
            self.val_odds.config(text=str(details["odds_count"]))
            self.val_unresolved.config(text=str(details["unresolved_count"]))
            self._show_packet(details["packet_text"], details["llm_packet_text"])
            self.btn_copy.config(state="normal")
            self._refresh_context_button()
        elif _is_completed_gated_capture(result):
            details = _gated_result_details(result)
            self.lbl_status.config(text="ZABLOKOWANE / JAKOŚĆ", foreground=self.accent_orange)
            self.lbl_status_msg.config(
                text=(f"Pobrano {details['odds_count']} kursów | nierozwiązane: {details['unresolved_count']} | "
                      f"CORE blokery: {details['core_blockers']} | {details['reason']}")[:180]
            )
            self.progress["value"] = 100
            self.val_groups.config(text=str(result.get("market_group_count", 0)))
            self.val_markets.config(text=str(result.get("market_count", 0)))
            self.val_odds.config(text=str(details["odds_count"]))
            self.val_unresolved.config(text=str(details["unresolved_count"]))
            self._show_packet(details["packet_text"], details["llm_packet_text"])
            self.btn_copy.config(state="normal")
            self._refresh_context_button()
        else:
            self.lbl_status.config(text="BŁĄD", foreground=self.accent_red)
            err = result.get("error", "Błąd podczas pobierania.")
            self.lbl_status_msg.config(text=f"Błąd: {err[:70]}")
            self.progress["value"] = 0
            messagebox.showerror("Błąd pobierania", f"Nie udało się pobrać kursów:\n\n{err}")

    def _show_packet(self, packet_text: str, llm_packet_text: str) -> None:
        # The internal packet stays in memory for the Context Engine only; the
        # preview and the copy button always carry the clean LLM odds text.
        self.current_packet = packet_text
        self.txt_preview.delete("1.0", tk.END)
        self.txt_preview.insert("1.0", llm_packet_text)

    def copy_packet(self) -> None:
        content = self.txt_preview.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Brak danych", "Brak pakietu do skopiowania.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.root.update()
        messagebox.showinfo("Skopiowano", "Pakiet kursowy skopiowany do schowka!")

    def _refresh_context_button(self) -> None:
        ready = packet_is_ready(self.current_packet) and not self.is_running and not self.context_is_running
        self.btn_context.config(state="normal" if ready else "disabled")
        self.lbl_context_status.config(
            text="CONTEXT: READY" if ready else "CONTEXT: BLOCKED",
            foreground=self.accent_blue if ready else self.accent_orange,
        )

    def start_context_build(self) -> None:
        if self.context_is_running:
            return
        if not packet_is_ready(self.current_packet):
            self._refresh_context_button()
            messagebox.showinfo("Context Engine", "Brak kompletnego pakietu gotowego do analizy kontekstu.")
            return
        self.context_is_running = True
        self.btn_context.config(state="disabled")
        self.lbl_context_status.config(text="CONTEXT: WORKING", foreground=self.accent_orange)
        threading.Thread(target=self._context_worker, args=(self.current_packet,), daemon=True).start()

    def _context_worker(self, packet_text: str) -> None:
        module_root = Path(__file__).resolve().parent
        output_dir = BASE_DIR / "context_outputs"
        result = run_context_engine(packet_text, module_root, output_dir, timeout_seconds=30.0)
        self.root.after(0, lambda: self._on_context_done(result))

    def _on_context_done(self, result: ContextRunResult) -> None:
        self.context_is_running = False
        if result.status in {"PASS", "PASS_WITH_QUARANTINE"} and result.json_path and result.text_path and result.text_path.is_file():
            self.lbl_context_status.config(text=f"CONTEXT: {result.status}", foreground=self.accent_green)
            report_text = result.text_path.read_text(encoding="utf-8")
            self.root.clipboard_clear()
            self.root.clipboard_append(report_text)
            self.root.update()
            try:
                os.startfile(result.text_path)
            except OSError:
                pass
            messagebox.showinfo(
                f"Context Engine — {result.status}",
                f"STATUS={result.status}\nJSON={result.json_path}\nTXT={result.text_path}\n\nRaport TXT skopiowano do schowka.",
            )
        else:
            reason = result.reason or "CONTEXT_ENGINE_BLOCKED"
            self.lbl_context_status.config(text="CONTEXT: BLOCKED", foreground=self.accent_orange)
            messagebox.showwarning("Context Engine — BLOCKED", f"STATUS=BLOCKED\nREASON={reason[:300]}")
        ready = packet_is_ready(self.current_packet) and not self.is_running and not self.context_is_running
        self.btn_context.config(state="normal" if ready else "disabled")


def main() -> None:
    if "--release-e2e" in os.sys.argv:
        from release_self_test import run_release_e2e

        position = os.sys.argv.index("--release-e2e")
        url = os.sys.argv[position + 1] if len(os.sys.argv) > position + 1 else ""
        raise SystemExit(run_release_e2e(url))
    root = tk.Tk()
    BetclicExtractorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
