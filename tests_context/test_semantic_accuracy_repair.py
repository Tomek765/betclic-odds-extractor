from __future__ import annotations

from dataclasses import replace

from apex_context_engine.anomalies import detect_anomalies
from apex_context_engine.engine import build_context
from apex_context_engine.inference import infer_market_script
from apex_context_engine.market_graph import best_price_alerts, build_fair_markets, canonical_signature, semantic_safety_quarantine
from apex_context_engine.models import OddRecord, ParsedPacket
from apex_context_engine.packet_parser import _compound_outcome, _double_chance_outcome
from apex_context_engine.report import render_json, render_text


def rec(family="1X2", market="Wynik", period="FULL_TIME", owner="", selection="HOME", line="", odds=2.0, raw="", scope="ANYTIME", outcome=""):
    return OddRecord("X", family, market, period, owner, selection, line, "", "", "WIN_LOSE", odds, raw=raw, scorer_scope=scope, canonical_outcome=outcome)


def scorer(*, market="Strzelec", selection="JAKUB ARAK", participant="JAKUB ARAK", owner="Polonia Bytom", period="FULL_TIME", scope="ANYTIME", settlement="WIN_LOSE", raw="Jakub Arak 2.50", source_ids=("capture:15",), teams=("Polonia Bytom", "Pogoń Grodzisk Mazowiecki")):
    return OddRecord("Strzelcy", "GOALSCORER", market, period, owner, selection, "", "", "", settlement, 2.5,
                     raw=raw, scorer_scope=scope, participant=participant,
                     source_raw_record_ids=source_ids, event_teams=teams)


def packet(rows, header=None, quarantined=None):
    source_q = sum(row.get("block_type") == "ODD" for row in (quarantined or []))
    return ParsedPacket(header or {"MATCH": "Benfica - Heart of Midlothian", "COMPETITION": "UEFA", "ANALYSIS_READY": "YES", "CLEAN_CORE_READY": "YES", "FULL_USABLE_READY": "YES"}, rows, source_odd_count=len(rows) + source_q, quarantined_rows=quarantined or [], normalized_text_sha256="0" * 64)


def fair_core(extra=()):
    rows = [rec(selection="HOME", odds=1.1), rec(selection="DRAW", odds=9), rec(selection="AWAY", odds=25)]
    for owner, family, lines in (("Benfica", "TEAM_TOTALS_HOME", [(1.5, 1.12, 4.8), (2.5, 1.43, 2.5), (3.5, 2.08, 1.62)]), ("Heart of Midlothian", "TEAM_TOTALS_AWAY", [(.5, 1.95, 1.7), (1.5, 5.4, 1.1), (2.5, 30, 1.01)])):
        for line, over, under in lines:
            rows += [rec(family, "TT", owner=owner, selection="OVER", line=f"{line:g}", odds=over), rec(family, "TT", owner=owner, selection="UNDER", line=f"{line:g}", odds=under)]
    rows += [rec("GOALS_OU", "Total", selection="OVER", line="2.5", odds=1.45), rec("GOALS_OU", "Total", selection="UNDER", line="2.5", odds=2.45)]
    return rows + list(extra)


def test_1x_12_x2_are_distinct():
    assert [_double_chance_outcome(raw, "Benfica", "Heart of Midlothian") for raw in ("Benfica lub remis 1.02", "Benfica lub Heart of Midlothian 1.04", "Remis lub Heart of Midlothian 6.60")] == ["1X", "12", "X2"]


def test_double_chance_ft_1h_2h_distinct():
    rows = [rec("DOUBLE_CHANCE", "DC", p, selection="X", odds=o, outcome=out) for p, o, out in (("FULL_TIME", 1.04, "12"), ("FULL_TIME", 6.6, "X2"), ("1ST_HALF", 1.17, "12"), ("1ST_HALF", 2.97, "X2"), ("2ND_HALF", 1.13, "12"), ("2ND_HALF", 3.3, "X2"))]
    assert len({canonical_signature(x) for x in rows}) == 6 and not best_price_alerts(rows)


def test_result_and_first_goal_team_components():
    values = [_compound_outcome("FIRST_GOAL_TEAM", "Wynik i kto zdobędzie 1. bramkę", raw, "Benfica", "Heart of Midlothian") for raw in ("Benfica / Benfica strzeli pierwszy 1.16", "Benfica / Heart of Midlothian strzeli pierwszy 7.00", "Remis / Benfica strzeli pierwszy 20")]
    assert values == ["FINAL_RESULT=HOME;FIRST_GOAL_TEAM=HOME", "FINAL_RESULT=HOME;FIRST_GOAL_TEAM=AWAY", "FINAL_RESULT=DRAW;FIRST_GOAL_TEAM=HOME"]


def test_scorer_anytime_2plus_3plus_distinct():
    rows = [rec("GOALSCORER", "Strzelcy", selection="PAVLIDIS", odds=o, scope=s) for o, s in ((1.33, "ANYTIME"), (35, "TWO_OR_MORE_GOALS"), (43, "THREE_OR_MORE_GOALS"))]
    assert len({canonical_signature(x) for x in rows}) == 3


def test_scorer_first_last_distinct():
    a, b = rec("GOALSCORER", "Strzelcy", selection="PAVLIDIS", scope="FIRST_GOAL"), rec("GOALSCORER", "Strzelcy", selection="PAVLIDIS", scope="LAST_GOAL")
    assert canonical_signature(a) != canonical_signature(b)


def test_ambiguous_scorer_quarantine():
    assert semantic_safety_quarantine([scorer(scope="")])[0]["reason"] == "AMBIGUOUS_GOALSCORER_SCOPE"


def test_named_anytime_scorer_with_complete_evidence_is_semantically_safe():
    assert semantic_safety_quarantine([scorer()]) == []


def test_named_first_scorer_with_complete_evidence_is_semantically_safe():
    assert semantic_safety_quarantine([scorer(market="Pierwszy strzelec", scope="FIRST_GOAL")]) == []


def test_named_scorer_with_hyphenated_identity_is_semantically_safe():
    assert semantic_safety_quarantine([scorer(selection="JEAN-PIERRE TEST", participant="JEAN-PIERRE TEST", raw="Jean-Pierre Test 2.50")]) == []


def test_scorer_missing_player_is_quarantined():
    assert semantic_safety_quarantine([scorer(selection="", participant="")])[0]["reason"] == "SCORER_PLAYER_IDENTITY_MISSING"


def test_scorer_foreign_owner_is_quarantined():
    assert semantic_safety_quarantine([scorer(owner="Foreign FC")])[0]["reason"] == "SCORER_OWNER_OUTSIDE_EVENT"


def test_scorer_player_conflict_is_quarantined():
    assert semantic_safety_quarantine([scorer(participant="KAMIL WOJTYRA")])[0]["reason"] == "SCORER_PLAYER_IDENTITY_CONFLICT"


def test_scorer_scope_conflict_and_invalid_settlement_are_quarantined():
    assert semantic_safety_quarantine([scorer(market="Pierwszy strzelec")])[0]["reason"] == "SCORER_SCOPE_CONFLICT"
    assert semantic_safety_quarantine([scorer(settlement="PUSH_ON_DRAW")])[0]["reason"] == "SCORER_SETTLEMENT_INVALID"


def test_scorer_quarantine_preserves_provenance():
    row = semantic_safety_quarantine([scorer(scope="")])[0]
    assert row["source_raw_record_ids"] == ["capture:15"]
    assert row["participant"] == "JAKUB ARAK" and row["raw_evidence"] == "Jakub Arak 2.50"


def test_clean_control_with_modeled_known_not_modeled_and_named_scorers_passes():
    known_not_modeled = rec("GOAL_PARITY", "Parzystość goli", selection="YES", odds=1.9)
    rows = fair_core((known_not_modeled, scorer(), scorer(market="Pierwszy strzelec", scope="FIRST_GOAL")))
    context = build_context(packet(rows))
    assert context.status == "PASS"
    assert context.semantic_safety_quarantine == []


def test_mixed_control_with_real_ambiguity_remains_fail_closed():
    real_ambiguity = [{"block_type": "ODD", "source_index": 99, "reasons": ["AMBIGUOUS_COMPOUND_OUTCOME"]}]
    context = build_context(packet(fair_core((scorer(),)), quarantined=real_ambiguity))
    assert context.status == "PASS_WITH_QUARANTINE"
    assert context.quarantined_source_rows == 1


def test_scorer_safety_is_deterministic_under_permutation():
    rows = [scorer(), scorer(market="Pierwszy strzelec", scope="FIRST_GOAL")]
    assert semantic_safety_quarantine(rows) == semantic_safety_quarantine(list(reversed(rows))) == []


def test_non_scorer_ignores_scorer_scope():
    a = rec(scope="FIRST_GOAL"); assert canonical_signature(a) == canonical_signature(replace(a, scorer_scope="LAST_GOAL"))


def test_compound_market_not_binary_pair():
    rows = [rec("BTTS", "Wynik meczu & oba zespoły strzelą", selection="HOME / TAK")]
    _, warnings = build_fair_markets(packet(rows)); assert not any(x.startswith("INCOMPLETE_MARKET") for x in warnings)


def test_team_lambda_without_zero_point_five():
    markets, _ = build_fair_markets(packet(fair_core())); script, _ = infer_market_script(packet([]).header, markets); assert 3.30 <= script["lambda_home"] <= 3.60


def test_robust_lambda_reconciliation():
    markets, _ = build_fair_markets(packet(fair_core())); script, _ = infer_market_script(packet([]).header, markets); assert script["reconciled_lambda_total"] and script["lambda_fit_residual"]["home"] is not None


def test_central_scores():
    markets, _ = build_fair_markets(packet(fair_core())); assert infer_market_script(packet([]).header, markets)[0]["central_scores"]


def test_primary_scoring_owner():
    context = build_context(packet(fair_core())); assert context.offense_map["primary_scoring_owner"] == "Benfica"


def test_monotonic_handicap_curve_no_naive_result_tension():
    context = build_context(packet(fair_core())); assert not any(x["type"] == "RESULT_VS_HANDICAP_TENSION" for x in context.anomalies)


def test_skellam_ready_inputs_are_exposed():
    context = build_context(packet(fair_core())); assert context.market_script["lambda_home"] is not None and context.market_script["lambda_away"] is not None


def test_status_pass_with_quarantine():
    q = [{"block_type": "ODD", "reasons": ["X"]}]
    assert build_context(packet(fair_core(), quarantined=q)).status == "PASS_WITH_QUARANTINE"


def test_counter_reconciliation():
    q = [{"block_type": "ODD", "reasons": ["X"]}, {"block_type": "EXCLUDED_MARKET", "reasons": ["UPSTREAM"]}]; c = build_context(packet(fair_core(), quarantined=q)); assert c.accepted_rows + c.quarantined_source_rows == c.source_odd_rows and c.source_odd_rows + c.upstream_excluded_rows == c.total_observed_rows


def test_semantic_collision_outlier_guard():
    a = rec(odds=1.1); b = replace(a, odds=2.2, category="Y"); assert not best_price_alerts([a, b])
    result = rec(odds=2.0, selection="HOME", outcome="HOME")
    handicap = rec("HANDICAP_EUROPEAN", "Handicap (2-way)", selection="HOME", line="-0.5", odds=2.2, outcome="HOME")
    handicap = replace(handicap, handicap_kind="TWO_WAY", handicap_taxonomy="TWO_WAY_NO_DRAW", settlement="NO_PUSH", category="Y")
    assert best_price_alerts([result, handicap])[0]["allowlist_rule"].startswith("1X2_HOME_EQ")


def test_deterministic_json():
    c = build_context(packet(fair_core())); assert render_json(c) == render_json(c)


def test_deterministic_txt():
    c = build_context(packet(fair_core())); assert render_text(c) == render_text(c) and "[EXECUTIVE_CONTEXT]" in render_text(c)
