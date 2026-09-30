from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from .models import ContextPacket


def render_json(context: ContextPacket) -> str:
    return json.dumps(context.to_dict(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def render_text(context: ContextPacket) -> str:
    data = context.to_dict()
    truth, script = data["input_truth"], data["market_script"]
    top_anomalies = data["anomalies"][:5]
    executive = [
        "APEX_CONTEXT_REPORT_V1", "", "[EXECUTIVE_CONTEXT]",
        f"STATUS={data['status']}",
        "INPUT_READINESS=" + json.dumps({key: truth.get(key) for key in ("ANALYSIS_READY", "CLEAN_CORE_READY", "FULL_USABLE_READY")}, ensure_ascii=False, sort_keys=True),
        f"FAIR_1X2={json.dumps(script.get('fair_1x2', {}), ensure_ascii=False, sort_keys=True)}",
        f"LAMBDA_HOME={script.get('lambda_home')}", f"LAMBDA_AWAY={script.get('lambda_away')}",
        f"LAMBDA_TOTAL={script.get('lambda_total')}", f"RECONCILED_LAMBDA_TOTAL={script.get('reconciled_lambda_total')}",
        f"TEAM_COMPONENT_SUM={script.get('team_component_sum')}",
        f"LAMBDA_RECONCILIATION_RESIDUAL={script.get('lambda_reconciliation_residual')}",
        f"LAMBDA_RECONCILIATION_RESIDUAL_PERCENT={script.get('lambda_reconciliation_residual_percent')}",
        f"RECONCILIATION_METHOD={script.get('reconciliation_method')}",
        f"PRIMARY_SCORING_OWNER={data['offense_map'].get('primary_scoring_owner')}",
        f"CENTRAL_SCORES={','.join(row['score'] for row in script.get('central_scores', [])[:5])}",
        "OFFENSE_SUMMARY=" + json.dumps(data["offense_map"].get("metrics", {}), ensure_ascii=False, sort_keys=True),
        "TRUSTED_ANOMALIES=" + json.dumps(top_anomalies, ensure_ascii=False, sort_keys=True),
        f"REJECTED_SEMANTIC_ALERTS={data['equivalence_audit'].get('semantic_collision_alerts_suppressed', 0) + len(data['semantic_safety_quarantine'])}",
        f"QUARANTINE_SUMMARY=SOURCE:{data['quarantined_source_rows']};UPSTREAM:{data['upstream_excluded_rows']};SEMANTIC_SAFETY:{len(data['semantic_safety_quarantine'])}", "",
    ]
    lines = [
        *executive, f"STATUS={data['status']}", f"INPUT_SHA256={data['input_sha256']}",
        "LABEL=MARKET_IMPLIED_CONTEXT_ONLY", "", "[BLOCKED_REASONS]",
        *(data["blocked_reasons"] or ["NONE"]), "", "[INPUT_TRUTH]",
        *(f"{key}={truth[key]}" for key in sorted(truth)), "", "[MARKET_SCRIPT]",
        f"HOME={script.get('home')}", f"AWAY={script.get('away')}",
        f"FAIR_1X2={json.dumps(script.get('fair_1x2', {}), ensure_ascii=False, sort_keys=True)}",
        f"DRAW_GRAVITY={script.get('draw_gravity')}", f"FAVORITE_STRENGTH={script.get('favorite_strength')}",
        f"LAMBDA_HOME={script.get('lambda_home')}", f"LAMBDA_AWAY={script.get('lambda_away')}",
        f"LAMBDA_TOTAL={script.get('lambda_total')}", f"GOAL_ENVIRONMENT={script.get('goal_environment')}",
        f"CENTRAL_SCORES={','.join(row['score'] for row in script.get('central_scores', []))}",
        f"SOURCES={json.dumps(script.get('sources', []), ensure_ascii=False)}",
        f"LIMITATIONS={json.dumps(script.get('limitations', []), ensure_ascii=False)}", "", "[OFFENSE_MAP]",
        json.dumps(data["offense_map"], ensure_ascii=False, sort_keys=True), "", "[LINE_DISCIPLINE]",
        json.dumps(data["line_discipline"], ensure_ascii=False, sort_keys=True), "", "[EQUIVALENCE_AUDIT]",
        json.dumps(data["equivalence_audit"], ensure_ascii=False, sort_keys=True), "", "[BEST_PRICE_ALERTS]",
    ]
    lines.extend(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in data["best_price_alerts"])
    if not data["best_price_alerts"]:
        lines.append("NONE")
    lines.extend(["", "[ANOMALIES]"])
    lines.extend(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in data["anomalies"])
    if not data["anomalies"]:
        lines.append("NONE")
    lines.extend([
        "", "[ROW_VALIDATION]",
        f"ACCEPTED_ROWS={data['accepted_rows']}",
        f"QUARANTINED_ROWS={len(data['quarantined_rows'])}",
        f"SOURCE_ODD_ROWS={data['source_odd_rows']}",
        f"ACCEPTED_SOURCE_ROWS={data['accepted_rows']}",
        f"QUARANTINED_SOURCE_ROWS={data['quarantined_source_rows']}",
        f"UPSTREAM_EXCLUDED_ROWS={data['upstream_excluded_rows']}",
        f"TOTAL_OBSERVED_ROWS={data['total_observed_rows']}",
        f"QUARANTINE_REASONS={json.dumps(data['quarantine_reasons'], ensure_ascii=False, sort_keys=True)}",
        f"QUARANTINED_RECORDS={json.dumps(data['quarantined_rows'], ensure_ascii=False, sort_keys=True)}",
        f"UPSTREAM_EXCLUSIONS={json.dumps(data['upstream_exclusions'], ensure_ascii=False, sort_keys=True)}",
        f"SEMANTIC_SAFETY_QUARANTINE={json.dumps(data['semantic_safety_quarantine'], ensure_ascii=False, sort_keys=True)}",
        f"WARNING_DISPOSITIONS={json.dumps(data['warning_dispositions'], ensure_ascii=False, sort_keys=True)}",
        f"CORE_COVERAGE={json.dumps(data['core_coverage'], ensure_ascii=False, sort_keys=True)}",
        f"OPTIONAL_COVERAGE={json.dumps(data['optional_coverage'], ensure_ascii=False, sort_keys=True)}",
        f"UNSUPPORTED_FAMILIES={json.dumps(data['unsupported_families'], ensure_ascii=False)}",
        f"SEMANTIC_RESOLUTIONS={len(data['semantic_resolutions'])}",
        "", "[WARNINGS]", *(data["warnings"] or ["NONE"]),
    ])
    return "\n".join(lines) + "\n"


def _pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _num(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"


_SIDE_ORDER = ("HOME", "DRAW", "AWAY", "OVER", "UNDER", "TAK", "NIE", "YES", "NO")


def _probabilities(selections: dict) -> str:
    keys = sorted(selections, key=lambda key: (_SIDE_ORDER.index(key) if key in _SIDE_ORDER else 99, key))
    return " ".join(f"{key} {_pct(selections[key])}" for key in keys)


def render_match_context(context: ContextPacket) -> str:
    """Market-implied match context for pasting into an LLM.

    Built independently from the odds package: it carries what the engine
    derives from the whole market (fair 1X2, goal expectation, likely scores,
    per-market fair probabilities, line interplay, price anomalies), not the
    list of bets.  No lineage ids, hashes, record dumps or audit mappings.
    """
    data = context.to_dict()
    truth, script = data["input_truth"], data["market_script"] or {}
    offense, discipline = data["offense_map"] or {}, data["line_discipline"] or {}
    lines = ["APEX_MATCH_CONTEXT"]
    lines += [f"{key}={' '.join(str(truth.get(key) or '').split())}" for key in ("MATCH", "COMPETITION", "KICKOFF")]
    lines += [f"STATUS={data['status']}", "LABEL=MARKET_IMPLIED_CONTEXT_ONLY"]
    if data["status"] == "BLOCKED":
        lines.append("BLOCKED_REASONS=" + ",".join(data["blocked_reasons"]))
        return "\n".join(lines) + "\n"

    fair = script.get("fair_1x2") or {}
    half = script.get("half_distribution") or {}
    confidence = script.get("lambda_confidence") or {}
    lines += ["", "[MARKET_SCRIPT]",
              f"HOME={script.get('home', '')}", f"AWAY={script.get('away', '')}",
              "FAIR_1X2=" + _probabilities(fair),
              f"FAVORITE_STRENGTH={script.get('favorite_strength', '')}",
              f"DRAW_GRAVITY={script.get('draw_gravity', '')}",
              f"GOAL_ENVIRONMENT={script.get('goal_environment', '')}",
              f"EXPECTED_GOALS=HOME {_num(script.get('lambda_home'))} AWAY {_num(script.get('lambda_away'))} "
              f"TOTAL {_num(script.get('reconciled_lambda_total') or script.get('lambda_total'))}",
              "EXPECTED_GOALS_CONFIDENCE=" + " ".join(f"{k.upper()} {v}" for k, v in sorted(confidence.items())),
              "CENTRAL_SCORES=" + " ".join(f"{row['score']} {_pct(row['probability'])}"
                                           for row in script.get("central_scores", [])),
              "GOAL_PROBABILITIES=" + " ".join(f"{key.upper()} {_pct(value)}" for key, value
                                               in sorted((script.get("goal_probabilities") or {}).items()))]
    if half.get("status") == "READY":
        lines.append(f"GOAL_SHARE_BY_HALF=1H {_pct(half.get('first_half_share'))} 2H {_pct(half.get('second_half_share'))}")
    if script.get("limitations"):
        lines.append("LIMITATIONS=" + ",".join(script["limitations"]))

    if offense.get("status") == "READY":
        lines += ["", "[OFFENSE]", f"PRIMARY_SCORING_OWNER={offense.get('primary_scoring_owner', '')}"]
        lines += [f"{key}={_pct(value.get('probability'))} {value.get('label', '')}"
                  for key, value in sorted((offense.get("metrics") or {}).items())]
        lines += [f"{period}_ANY_GOAL={_pct(value.get('probability'))} {value.get('label', '')}"
                  for period, value in sorted((offense.get("period_offense") or {}).items())]

    lines += ["", "[FAIR_MARKETS]", "FAMILY|MARKET|PERIOD|OWNER|LINE|FAIR_PROBABILITIES|MARGIN"]
    for market in data["fair_markets"]:
        lines.append("|".join([market["family"], market["market"], market["period"], market.get("owner", ""),
                               str(market.get("line", "")), _probabilities(market.get("selections") or {}),
                               _pct((market.get("overround") or 1) - 1)]))

    if discipline.get("status") == "READY":
        lines += ["", "[LINE_DISCIPLINE]"]
        lines += [f"WARNING={warning}" for warning in discipline.get("cross_market_warnings", [])]
        lines += [f"SCORE {row['score']}: " + ", ".join(row.get("effects", []))
                  for row in discipline.get("natural_score_scenarios", [])]

    if data["best_price_alerts"]:
        lines += ["", "[BETTER_PRICE_SAME_SETTLEMENT]"]
        seen_lines: set[str] = set()
        for alert in data["best_price_alerts"]:
            best = alert.get("best") or {}
            for copy in alert.get("worse_copies", []):
                # The same offer shown on two tabs renders identically; list it once.
                line = (f"{best.get('market')} {best.get('odds')} vs {copy.get('market')} {copy.get('odds')} "
                        f"(+{float(copy.get('gain_percent', 0)):.1f}%)")
                if line not in seen_lines:
                    seen_lines.add(line)
                    lines.append(line)

    diagnostics = quarantine_diagnostics(context)
    excluded = Counter(row["reason_code"] for row in diagnostics if row["quarantine"])
    not_modeled = Counter(row["reason_code"] for row in diagnostics if not row["quarantine"])
    lines += ["", "[DATA_QUALITY]",
              f"QUARANTINED_BETS={sum(excluded.values())}" + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(excluded.items())) + ")" if excluded else ""),
              f"NOT_MODELED_BETS={sum(not_modeled.values())}" + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(not_modeled.items())) + ")" if not_modeled else "")]
    by_reason: dict[str, Counter] = {}
    for row in diagnostics:
        if row["quarantine"]:
            by_reason.setdefault(row["reason_code"], Counter())[row["market_name"]] += 1
    for code in sorted(by_reason):
        ranked = sorted(by_reason[code].items(), key=lambda item: (-item[1], item[0]))
        shown = "; ".join(f"{name} x{count}" for name, count in ranked[:6])
        rest = len(ranked) - 6
        lines.append(f"QUARANTINED_MARKETS {code}: {shown}" + (f"; +{rest} more markets" if rest > 0 else ""))
    contradictions = [row["evidence"] for row in data["anomalies"] if row.get("type") == "EQUIVALENCE_PRICE_CONTRADICTION"]
    if contradictions:
        lines.append(f"PRICE_CONTRADICTIONS={len(contradictions)} (same settlement priced >50% apart; not offered as better price)")
        for row in contradictions:
            lines.append("CONTRADICTION " + " vs ".join(f"{market} {odds}" for market, _category, odds in row["markets"]))
    return "\n".join(lines) + "\n"


QUARANTINE_REASON_DETAILS = {
    "UNCONFIRMED_XTRA_PAYOUT_CONTRACT": "Xtra Wygrana payout rules are not established; odds are not comparable.",
    "UNCONFIRMED_TEAM_OWNER": "Team market without a proven owning team.",
    "UNCONFIRMED_PLAYER_PROP_SCOPE": "Player market without a proven player.",
    "UNCONFIRMED_PLAYER_PROP_PERIOD": "Player market whose settlement period is not stated or documented.",
    "UNSUPPORTED_OPTIONAL_STATISTICS_PERIOD": "Statistics market whose settlement period is not stated or documented.",
    "UNCONFIRMED_MARKET_PERIOD": "Market whose settlement period is not stated or documented.",
    "UNCONFIRMED_MARKET_SETTLEMENT": "Market family or payout shape not recognised.",
    "UNSUPPORTED_PERIOD:OTHER": "Explicit non-regular period (extra time, penalties); valid bet, not priced by the model.",
    "UNSUPPORTED_PERIOD:QUALIFICATION": "Qualification market; valid bet, not priced by the model.",
    "AMBIGUOUS_COMPOUND_OUTCOME": "Selection could not be mapped to one outcome of the event.",
    "SCORER_PLAYER_IDENTITY_MISSING": "Scorer market without a proven player name.",
    "AMBIGUOUS_GOALSCORER_SCOPE": "Scorer scope (anytime/first/last) not proven.",
}


def _reason_code(reason: str) -> str:
    return reason.split(":", 1)[1] if reason.startswith("EXTRACTOR_SEMANTIC_QUARANTINE:") else reason


def quarantine_diagnostics(context: ContextPacket) -> list[dict[str, object]]:
    """One explainable row per excluded bet: where, why and whether it is a real quarantine."""
    rows: list[dict[str, object]] = []

    def record_id(row: dict) -> str:
        fields = row.get("original_fields") or {}
        return str(fields.get("RAW_RECORD_ID") or fields.get("SOURCE_RAW_RECORD_IDS")
                   or ",".join(row.get("source_raw_record_ids") or []) or row.get("source_record_id")
                   or f"ODD:{row.get('source_index', '')}")

    for stage, source, is_quarantine in (("EXTRACTOR_SEMANTIC", context.upstream_exclusions, True),
                                         ("PACKET_VALIDATION", context.quarantined_rows, True),
                                         ("PACKET_VALIDATION", context.not_modeled_rows, False),
                                         ("SEMANTIC_SAFETY", context.semantic_safety_quarantine, True)):
        for row in source:
            reasons = [_reason_code(str(r)) for r in (row.get("reasons") or [row.get("reason", "")])]
            code = ",".join(reasons)
            rows.append({"record_id": record_id(row), "market_name": row.get("market", ""),
                         "selection": row.get("selection", ""), "quarantine": is_quarantine,
                         "disposition": "QUARANTINE" if is_quarantine else "NOT_MODELED",
                         "reason": code, "reason_code": code,
                         "reason_details": " ".join(QUARANTINE_REASON_DETAILS.get(r, r) for r in reasons),
                         "source_stage": stage,
                         "source_context": str((row.get("original_fields") or {}).get("BOX_CONTEXT", ""))})
    return sorted(rows, key=lambda row: (row["source_stage"], str(row["record_id"]), str(row["market_name"])))


def write_outputs(context: ContextPacket, output_dir: str | Path) -> tuple[Path, Path]:
    """Write the user-facing match context and the internal diagnostics.

    APEX_CONTEXT_REPORT.txt is what the application copies and opens: the
    clean market context (render_match_context), never the odds package.
    The full audit (APEX_CONTEXT_AUDIT.txt), the JSON packet and the per-record
    quarantine explanations (APEX_QUARANTINE_DIAGNOSTICS.json) stay internal.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, text_path = out / "APEX_CONTEXT_PACKET.json", out / "APEX_CONTEXT_REPORT.txt"
    audit_path, diagnostics_path = out / "APEX_CONTEXT_AUDIT.txt", out / "APEX_QUARANTINE_DIAGNOSTICS.json"
    diagnostics = json.dumps(quarantine_diagnostics(context), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    for path, content in ((json_path, render_json(context)), (audit_path, render_text(context)),
                          (diagnostics_path, diagnostics), (text_path, render_match_context(context))):
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=out, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temp_name = handle.name
            Path(temp_name).replace(path)
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
    return json_path, text_path
