import json
from pathlib import Path
from core import partition_semantic_records, build_equivalence_groups
from parser import parse_market_record


def test_real_elche_match_xtra_never_declares_binary_payout():
    path = Path(__file__).parents[1]/'diagnostics/raw_before_dedupe_run_1787475817_15748.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    cases = [r for r in rows if r.get('market') == 'Wynik meczu - Xtra Wygrana']
    assert len(cases) == 4
    for r in cases:
        def parse(title):
            return parse_market_record(category=r['category'], market_title=title,
                raw_selection=r['selection'], odds_str=r['odds'], raw_text=r['raw'],
                section_title=r.get('section_title',''), home_team='Elche',away_team='Barcelona',
                container_id=r.get('container_id',''),market_instance_id=r.get('market_instance_id',''))
        row, issue = parse(r['market'])
        assert issue is None
        # Independently grounded in the captured market's explicit Xtra flag/name:
        # no ordinary binary payout is proven by its displayed numeric price.
        assert row['SETTLEMENT'] == row['PAYOUT_CONTRACT'] == 'UNKNOWN'
        assert 'PAYOUT_FORMULA' in row['CONTRACT_MISSING']
        assert partition_semantic_records([row]) == ([], [row])
        assert build_equivalence_groups([row]) == []
        ordinary, issue = parse('Wynik meczu (z wyłączeniem dogrywki)')
        assert issue is None
        assert ordinary['SETTLEMENT'] == 'WIN_LOSE'
        assert partition_semantic_records([ordinary]) == ([ordinary], [])
