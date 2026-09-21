import json
from dataclasses import replace
from pathlib import Path

from parser import parse_market_record
from apex_context_engine.models import OddRecord
from apex_context_engine.market_graph import best_price_alerts, canonical_signature


def real_player_records():
    path = Path(__file__).parents[1] / 'diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    records = []
    for row in rows:
        if row.get('market') != 'Zawodnik strzeli i powyżej 1,5 goli - 1. połowa' or row.get('section_title') != 'Barcelona':
            continue
        parsed, issue = parse_market_record(category=row['category'], market_title=row['market'],
            raw_selection=row['selection'], odds_str=row['odds'], raw_text=row['raw'],
            section_title=row['section_title'], home_team='Elche', away_team='Barcelona',
            container_id=row.get('container_id', ''), market_instance_id=row['market_instance_id'])
        assert issue is None
        assert parsed['PARTICIPANT'] == row['selection']
        records.append(OddRecord(**{key.lower(): parsed.get(key, '') for key in
            'CATEGORY FAMILY MARKET PERIOD OWNER SELECTION LINE HANDICAP_KIND HANDICAP_TAXONOMY SETTLEMENT'.split()},
            odds=float(parsed['ODDS']), participant=parsed['PARTICIPANT'],
            scorer_scope=parsed.get('SCORER_SCOPE', ''), raw=row['raw'], source_index=len(records),
            canonical_outcome=parsed['SELECTION']))
    assert {r.participant for r in records} == {'Raphinha', 'Lamine Yamal', 'Anthony Gordon'}
    return records


def test_different_real_players_cannot_create_best_price_alert():
    records = real_player_records()
    assert best_price_alerts(records) == []
    assert len({canonical_signature(r) for r in records}) == 3


def test_same_player_exact_copy_is_comparable_but_missing_identity_is_not():
    original = real_player_records()[0]
    cheaper = replace(original, odds=original.odds - .1, source_index=99, category='Top')
    assert len(best_price_alerts([original, cheaper])) == 1
    assert best_price_alerts([replace(original, participant=''), replace(cheaper, participant='')]) == []
    assert best_price_alerts([original, replace(cheaper, scorer_scope='DIFFERENT_SCOPE')]) == []
