"""Compare real replay with the actual production postprocessing statements."""
import ast
import copy
from pathlib import Path
from unittest.mock import patch

import core
import replay
from parser import parse_market_record

FIXTURE = Path(__file__).parent / 'fixtures/kaiserslautern_darmstadt/raw_before_dedupe_run_1788588979_12912.jsonl'


def test_real_capture_production_postprocessing_matches_replay():
    saved = []
    original = replay._dedupe_records_preserving_order
    def intercept(rows, issues):
        saved.extend(copy.deepcopy(rows))
        return original(rows, issues)
    with patch.object(replay, '_dedupe_records_preserving_order', side_effect=intercept):
        result = replay.replay_real_prematch(FIXTURE)
    raw = replay.load_real_prematch_fixture(FIXTURE)
    home, away = replay._capture_teams(raw)
    # Execute the actual production statements, so an accidental change of order,
    # resolver inputs, or population fails against replay on this real input.
    source = Path(core.__file__).read_text(encoding='utf-8')
    start = source.index('        unique_odds, unresolved_items = _dedupe_records_preserving_order(extracted_odds, unresolved_items)')
    end = source.index('        # COUNTERS', start)
    import textwrap
    code = compile(ast.parse(textwrap.dedent(source[start:end])), '<production boundary>', 'exec')
    ns = dict(vars(core), extracted_odds=saved, unresolved_items=[],
              raw_before_dedupe=raw, home_team=home, away_team=away)
    exec(code, ns)
    assert ns['unique_odds'] == result['odds']
    assert ns['core_semantic_quarantine'] == result['semantic_quarantine']
    assert ns['period_resolution'] == result['period_resolution']
    assert len(ns['canonical_export_all']) == result['production_accounting']['CANONICAL_ODDS_COUNT']
    assert len(ns['export_odds']) == result['production_accounting']['SEMANTIC_ACCEPTED_COUNT']
    assert len(ns['export_semantic_quarantine_rows']) == result['production_accounting']['SEMANTIC_QUARANTINED_COUNT']


def test_production_preserves_structural_evidence_before_dedupe():
    source = Path(core.__file__).read_text(encoding='utf-8')
    start = source.index('                    if odd_rec:')
    end = source.index('                    if unres_rec:', start)
    import textwrap
    block = compile(ast.parse(textwrap.dedent(source[start:end])), '<production provenance>', 'exec')
    for raw in replay.load_real_prematch_fixture(FIXTURE)[::37]:
        ns = dict(vars(core), odd_rec={}, ledger_entry={}, item=raw,
                  source_idx=raw['source_index'], run_id=raw['run_id'], event_id=raw['event_id'],
                  raw_record_id=raw['raw_record_id'], tab_name=raw['tab_name'], extracted_odds=[])
        ns['odd_rec'] = {'FAMILY': 'TEST'}
        exec(block, ns)
        expected = {}
        core.attach_structural_provenance(expected, raw)
        assert all(ns['odd_rec'][k] == v for k, v in expected.items())


def test_xtra_retains_declared_event_without_inventing_payout():
    titles = {'Strzelec - Xtra Wygrana': 'PLAYER_GOALS_GE_1',
              'Zawodnik zaliczy asystę - Xtra Wygrana': 'PLAYER_ASSISTS_GE_1',
              'Zawodnik strzeli gola lub zaliczy asystę - Xtra Wygrana': 'PLAYER_GOALS_PLUS_ASSISTS_GE_1'}
    for title, event in titles.items():
        row, issue = parse_market_record(category='Strzelcy', market_title=title,
            raw_selection='Ivan Prtajin', odds_str='2.00', raw_text='Ivan Prtajin 2.00',
            section_title='Kaiserslautern', home_team='Kaiserslautern', away_team='Darmstadt',
            container_id='real-title-contract', market_instance_id='real-title-contract', period_hint='90 min')
        assert issue is None
        assert row['DECLARED_WINNING_EVENT'] == event
        assert row['SETTLEMENT'] == row['PAYOUT_CONTRACT'] == 'UNKNOWN'
        assert core.partition_semantic_records([row]) == ([], [row])
        assert core.semantic_quarantine_ledger([row])[0]['reason'] == 'UNCONFIRMED_XTRA_PAYOUT_CONTRACT'
        assert not core.build_equivalence_groups([row])


def test_draw_alias_equivalence_is_period_and_contract_bounded():
    from dataclasses import replace
    from tests_context.test_run_1788588979_repair import odd
    from apex_context_engine.market_graph import _safe_equivalence_keys
    plain = odd(market='Wynik meczu', selection='DRAW', owner='')
    alias = replace(plain, market='Wynik meczu (z wyłączeniem dogrywki)')
    assert set(_safe_equivalence_keys(plain)) & set(_safe_equivalence_keys(alias))
    for variant in (replace(alias, period='2ND_HALF'), replace(alias, settlement='UNKNOWN'),
                    replace(alias, market='Wynik meczu - Xtra Wygrana')):
        assert not set(_safe_equivalence_keys(plain)) & set(_safe_equivalence_keys(variant))


def test_blocked_context_keeps_schema_valid_empty_graph():
    import json
    import jsonschema
    from apex_context_engine.packet_parser import parse_packet_text
    from apex_context_engine.engine import build_context
    root = Path(core.__file__).parent
    parsed = parse_packet_text((root/'tests_context/fixtures/minimal_packet.txt').read_text(encoding='utf-8'))
    for key in ('ANALYSIS_READY','CLEAN_CORE_READY','FULL_USABLE_READY'):
        parsed.header[key] = 'NO'
    result = build_context(parsed).to_dict()
    assert result['status'] == 'BLOCKED'
    assert result['market_graph'] == {'nodes': [], 'relations': []}
    assert result['fair_markets'] == []
    jsonschema.validate(result, json.loads((root/'schemas/apex_context_packet.schema.json').read_text(encoding='utf-8')))
