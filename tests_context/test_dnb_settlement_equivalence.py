from dataclasses import replace

import pytest

from apex_context_engine.market_graph import best_price_alerts
from apex_context_engine.models import OddRecord


def pair():
    dnb = OddRecord(category='Wynik', family='DNB', market='Remis - zwrot',
        period='FULL_TIME', owner='Home FC', selection='HOME', line='',
        handicap_kind='', handicap_taxonomy='', settlement='PUSH_ON_DRAW', odds=1.9,
        canonical_outcome='HOME', source_index=1)
    handicap = replace(dnb, family='HANDICAP_EUROPEAN', market='Handicap (2-drożny)',
        owner='', line='0', handicap_kind='TWO_WAY', handicap_taxonomy='TWO_WAY_NO_DRAW',
        settlement='PUSH_POSSIBLE', odds=2.0, source_index=2)
    return dnb, handicap


def test_dnb_and_zero_handicap_with_draw_refund_are_equivalent():
    assert len(best_price_alerts(pair())) == 1


@pytest.mark.parametrize('leg,changes', [
    (0, {'settlement': 'WIN_LOSE'}),
    (1, {'settlement': 'NO_PUSH'}),
    (0, {'line': '1'}),
    (1, {'period': '1ST_HALF'}),
    (1, {'handicap_kind': 'THREE_WAY', 'settlement': 'WIN_DRAW_LOSE'}),
])
def test_nonidentical_draw_refund_contracts_never_merge(leg, changes):
    # At 0:0 the valid contracts refund; WIN_LOSE/NO_PUSH cannot be assumed
    # to do so. A nonzero line and a different period change the event too.
    records = list(pair())
    records[leg] = replace(records[leg], **changes)
    assert best_price_alerts(records) == []
