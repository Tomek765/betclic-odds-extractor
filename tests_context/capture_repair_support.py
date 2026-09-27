"""Replay raw capture through the production parser and export boundary."""
import json
from pathlib import Path
from unittest.mock import patch

import replay
from core import (_dedupe_canonical_export_rows, derive_market_normalization,
                  partition_semantic_records, build_equivalence_groups,
                  semantic_quarantine_ledger)


def capture_packet(path):
    parsed = []
    original = replay.parse_market_record
    def collect(**kwargs):
        row, issue = original(**kwargs)
        if row:
            parsed.append(row)
        return row, issue
    with patch.object(replay, 'parse_market_record', side_effect=collect):
        result = replay.replay_real_prematch(path)
    home, away = replay._capture_teams(replay.load_real_prematch_fixture(path))
    derive_market_normalization(parsed, home, away)
    canonical, _, _ = _dedupe_canonical_export_rows(parsed)
    accepted, quarantined = partition_semantic_records(canonical)
    header = dict(MATCH=f'{home} - {away}', COMPETITION='Captured event',
                  PARSER_TRUTH_STATUS='PASS' if not result['unresolved_count'] else 'PARTIAL',
                  ANALYSIS_READY=result['analysis_ready'], CLEAN_CORE_READY=result['analysis_ready'],
                  FULL_USABLE_READY=result['full_usable_ready'], ODDS_COUNT=len(accepted),
                  UNRESOLVED_COUNT=result['unresolved_count'], COMPLETENESS_SCORE=result['completeness']['COMPLETENESS_PARSE'])
    def block(name, fields):
        return name+'{\n'+'\n'.join(f'{k}="{v}";' for k,v in fields.items())+'\n}\n'
    text = block('BETCLIC_FULL_ODDS_PACKET', header)
    keys = ('CATEGORY FAMILY MARKET PERIOD OWNER SELECTION LINE HANDICAP_KIND HANDICAP_TAXONOMY '
            'SETTLEMENT ODDS RAW PERIOD_SOURCE PERIOD_CONFIDENCE SCORER_SCOPE PARTICIPANT MARKET_INSTANCE_ID').split()
    for row in accepted:
        fields = {k:row.get(k,'') for k in keys}
        fields['PARTICIPANTS'] = ' + '.join(row.get('PARTICIPANTS') or [])
        fields['SOURCE_RAW_RECORD_IDS'] = ','.join(row.get('source_raw_record_ids') or [])
        text += block('ODD',fields)
    for group in build_equivalence_groups(accepted):
        text += 'EQUIVALENCE_GROUP{\nSIGNATURE="'+group['signature']+'";\nCOPIES='+json.dumps(group['copies'],ensure_ascii=False)+';\n}\n'
    for row in semantic_quarantine_ledger(quarantined):
        fields = {k.upper():v for k,v in row.items() if not isinstance(v,list)}
        fields['SOURCE_RAW_RECORD_IDS'] = ','.join(row.get('source_raw_record_ids') or [])
        text += block('SEMANTIC_QUARANTINE', fields)
    return text, result, canonical
