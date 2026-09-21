from __future__ import annotations

import json
import os
import tempfile
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


def write_outputs(context: ContextPacket, output_dir: str | Path) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, text_path = out / "APEX_CONTEXT_PACKET.json", out / "APEX_CONTEXT_REPORT.txt"
    for path, content in ((json_path, render_json(context)), (text_path, render_text(context))):
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
