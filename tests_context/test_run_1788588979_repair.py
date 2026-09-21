"""Real capture regression: identities, settlement proof and audit accounting."""
import json
from dataclasses import replace
from itertools import permutations
from pathlib import Path

from apex_context_engine.anomalies import detect_anomalies
from apex_context_engine.market_graph import audit_equivalence, _safe_equivalence_keys
from apex_context_engine.models import OddRecord, ParsedPacket
from apex_context_engine.packet_parser import parse_packet_text
from core import _settlement_signature
from parser import classify_period_detail

FIXTURE = Path(__file__).parent / 'fixtures/kaiserslautern_darmstadt'


def odd(**changes):
    values = dict(category='Wynik', family='1X2', market='Wynik meczu',
                  period='1ST_HALF', owner='Home FC', selection='HOME', line='',
                  handicap_kind='', handicap_taxonomy='', settlement='WIN_LOSE',
                  odds=3.2, source_raw_record_ids=('run:1',))
    values.update(changes)
    return OddRecord(**values)


def test_lineage_prevents_cross_period_lookup_collision():
    home = odd(source_index=1)
    draw = odd(period='2ND_HALF', owner='', selection='DRAW', source_index=2,
               source_raw_record_ids=('run:2',))
    handicap = odd(market='Handicap', family='HANDICAP_EUROPEAN', line='-0.5',
                   handicap_kind='TWO_WAY', settlement='NO_PUSH', odds=3.3,
                   source_index=3, source_raw_record_ids=('run:3',))
    copies = [dict(market=r.market, category=r.category, odds=str(r.odds),
                   source_raw_record_ids=list(r.source_raw_record_ids)) for r in (home, handicap)]
    for rows in permutations([home, draw, handicap]):
        audit = audit_equivalence(ParsedPacket({}, list(rows),
             equivalence_groups_raw=[{'SIGNATURE':'1ST_HALF|RESULT:HOME','COPIES':copies}]), [])
        assert len(audit['accepted_groups']) == 1
        assert audit['accepted_groups'][0]['matched_records'] == 2


def test_boolean_proof_and_integer_line_counterexample():
    left = odd(family='COMPOUND_LOGIC', market='Oba zespoły strzelą gola lub Powyżej 2,5 gola w meczu',
               selection='BTTS_OR_OVER_NO', line='2.5', owner='')
    right = replace(left, market='Oba zespoły strzelą gola / Liczba bramek', selection='BTTS_NO_AND_UNDER')
    assert set(_safe_equivalence_keys(left)) & set(_safe_equivalence_keys(right))
    assert not set(_safe_equivalence_keys(replace(left,line='2'))) & set(_safe_equivalence_keys(replace(right,line='2')))
    for home in range(12):
        for away in range(12):
            btts = home > 0 and away > 0
            assert (not (btts or home+away > 2.5)) == (not btts and home+away < 2.5)
    assert (not (False or 2 > 2)) != (not False and 2 < 2)


def test_upstream_boolean_does_not_equate_negated_under():
    row = dict(event_id='A|B', PERIOD='FULL_TIME', FAMILY='COMPOUND_LOGIC',
               MARKET='Oba zespoły strzelą gola lub Poniżej 2,5 gola w meczu',
               RAW='Nie 2.00', SELECTION='BTTS_OR_UNDER_NO', LINE='2.5', SETTLEMENT='WIN_LOSE')
    assert _settlement_signature(row) == ''


def test_statistic_line_scale_and_polish_metric():
    rows = [odd(family='EVENT_TOTAL', market='Liczba strzałów w meczu (OPTA)',
                category='Statystyki', line='30.5', owner='', period='FULL_TIME'),
            odd(family='EVENT_TOTAL', market='Liczba celnych strzałów zawodnika (OPTA)',
                category='Statystyki', line='99.5', participant='Jan Test')]
    alerts = detect_anomalies(ParsedPacket({}, rows), [], {}, [], {}, [])
    assert [x['evidence']['line'] for x in alerts if x['type']=='SUSPICIOUS_LINE'] == ['99.5']


def test_semantic_quarantine_blocks_are_losslessly_accounted():
    text = (Path(__file__).parent/'fixtures/minimal_packet.txt').read_text(encoding='utf-8')
    text += '\nSEMANTIC_QUARANTINE{\nFAMILY="PLAYER_PROP";\nMARKET="New market";\nPERIOD="UNKNOWN";\nREASON="UNCONFIRMED_PLAYER_PROP_PERIOD";\n}\n'
    packet = parse_packet_text(text)
    assert len(packet.quarantined_rows) == 1
    assert packet.quarantined_rows[0]['original_fields']['PERIOD'] == 'UNKNOWN'


def test_regulatory_periods_are_distinct_and_closed():
    cases = [('Zawodnik zaliczy asystę','PLAYER_PROP','FULL_TIME'),
             ('Liczba strzałów zawodnika (OPTA)','PLAYER_PROP','MATCH_INCLUDING_EXTRA_TIME'),
             ('1x2 Strzały (120 min)','1X2','MATCH_INCLUDING_EXTRA_TIME'),
             ('Rzuty rożne','EVENT_TOTAL','FULL_TIME'),
             ('Więcej kartek','EVENT_TOTAL','FULL_TIME')]
    for title,family,period in cases:
        assert classify_period_detail(title,'',family=family)[0] == period
    assert classify_period_detail('Nowy rynek zawodnika','',family='PLAYER_PROP')[0] == 'UNKNOWN'
    assert classify_period_detail('Nowy rynek (120 min)','',family='PLAYER_PROP')[0] == 'OTHER'
    assert classify_period_detail('Zawodnik zaliczy asystę (90 min)','',family='PLAYER_PROP')[0] == 'FULL_TIME'
    for title,family,_ in cases[:2]:
        for label,expected in [('1. połowa','1ST_HALF'),('2. połowa','2ND_HALF')]:
            assert classify_period_detail(title,label,family=family)[0] == expected


def test_real_capture_supported_player_contracts_are_not_false_quarantines():
    from tests_context.capture_repair_support import capture_packet
    from apex_context_engine.engine import build_context
    text, result, rows = capture_packet(FIXTURE/'raw_before_dedupe_run_1788588979_12912.jsonl')
    context = build_context(parse_packet_text(text))
    assert result['unresolved_count'] == 0
    assert len(rows) == 1018
    assert not [r for r in context.semantic_safety_quarantine if 'Xtra' not in r['market']]
    assert not context.equivalence_audit['rejected_groups']
    assert not [r for r in context.anomalies if r['type']=='SUSPICIOUS_LINE']


def test_period_accounting_names_every_population():
    from core import period_accounting
    counts = period_accounting([{'PERIOD':'FULL_TIME'}], [{'PERIOD':'UNKNOWN'}]*380,
                               [{'PERIOD':'UNKNOWN'}]*320)
    assert counts['PERIOD_UNKNOWN_COUNT'] == 380
    assert counts['CORE_ACCEPTED_PERIOD_UNKNOWN_COUNT'] == 0
    assert counts['CANONICAL_EXPORT_PERIOD_UNKNOWN_COUNT'] == 320


def test_warning_dispositions_do_not_degrade_status_and_keep_upstream_evidence():
    from apex_context_engine.engine import build_context
    from apex_context_engine.report import render_text
    text=(Path(__file__).parent/'fixtures/minimal_packet.txt').read_text(encoding='utf-8')
    context=build_context(parse_packet_text(text))
    assert context.status=='PASS'
    assert 'warning_dispositions' in context.to_dict()
    text+='\nSEMANTIC_QUARANTINE{\nMARKET="New market";\nPERIOD="UNKNOWN";\nREASON="UNCONFIRMED_MARKET_PERIOD";\n}\n'
    context=build_context(parse_packet_text(text))
    assert context.status=='PASS_WITH_QUARANTINE'
    assert context.upstream_exclusions[0]['original_fields']['PERIOD']=='UNKNOWN'
    assert 'UNCONFIRMED_MARKET_PERIOD' in render_text(context)


def test_canonical_export_is_nonmutating_and_permutation_invariant():
    from core import _dedupe_canonical_export_rows
    rows=[dict(CATEGORY='Top',MARKET='Wynik',PERIOD='1ST_HALF',SELECTION='HOME',ODDS='2.1',
               raw_record_id=f'run:{i}',source_raw_record_ids=[f'run:{i}'],MARKET_INSTANCE_ID=f'cell:{i}') for i in (1,2)]
    before=json.dumps(rows,sort_keys=True)
    first=_dedupe_canonical_export_rows(rows)
    assert json.dumps(rows,sort_keys=True)==before
    assert first==_dedupe_canonical_export_rows(list(reversed(rows)))


def test_conflicting_half_and_unsupported_window_fail_closed():
    assert classify_period_detail('Wynik - 1. połowa','2. połowa',family='1X2')[0]=='UNKNOWN'
    assert classify_period_detail('Wynik (150 min)','',family='1X2')[0]=='OTHER'


def test_real_capture_packet_is_invariant_to_observation_permutation(tmp_path):
    import random
    from tests_context.capture_repair_support import capture_packet
    source=FIXTURE/'raw_before_dedupe_run_1788588979_12912.jsonl'
    rows=source.read_text(encoding='utf-8').splitlines()
    random.Random(20260905).shuffle(rows)
    permuted=tmp_path/source.name
    permuted.write_text('\n'.join(rows)+'\n',encoding='utf-8')
    assert capture_packet(source)[0] == capture_packet(permuted)[0]
