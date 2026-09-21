from apex_context_engine.market_graph import audit_equivalence
from apex_context_engine.models import OddRecord, ParsedPacket


def odd(*, category, market, selection, odds, index, family="COMPOUND_LOGIC", owner="", line="2.5", outcome=""):
    return OddRecord(
        category=category,
        family=family,
        market=market,
        period="FULL_TIME",
        owner=owner,
        selection=selection,
        line=line,
        handicap_kind="",
        handicap_taxonomy="",
        settlement="WIN_LOSE",
        odds=odds,
        canonical_outcome=outcome or selection,
        source_index=index,
    )


def copy(record):
    return {"market": record.market, "category": record.category, "odds": record.odds}


def test_every_applied_equivalence_rule_is_declared_in_the_public_allowlist():
    compound_a = odd(
        category="Top",
        market="Oba zespoły strzelą gola lub powyżej 2,5 gola w meczu",
        selection="NO",
        odds=1.91,
        index=1,
        outcome="BTTS_OR_OVER_NO",
    )
    compound_b = odd(
        category="Gole",
        market="Oba zespoły strzelą gola / liczba bramek",
        selection="NO_AND_UNDER",
        odds=1.92,
        index=2,
        outcome="BTTS_NO_AND_UNDER",
    )
    draw_a = odd(
        category="Top",
        market="Wynik meczu",
        selection="DRAW",
        odds=3.2,
        index=3,
        family="1X2",
        line="",
    )
    draw_b = odd(
        category="Wynik",
        market="Wynik meczu",
        selection="DRAW",
        odds=3.3,
        index=4,
        family="1X2",
        line="",
    )
    packet = ParsedPacket(
        header={},
        odds=[compound_a, compound_b, draw_a, draw_b],
        equivalence_groups_raw=[
            {"SIGNATURE": "compound", "COPIES": [copy(compound_a), copy(compound_b)]},
            {"SIGNATURE": "draw", "COPIES": [copy(draw_a), copy(draw_b)]},
        ],
    )

    audit = audit_equivalence(packet, [])

    assert len(audit["accepted_groups"]) == 2
    applied = {
        rule
        for group in audit["accepted_groups"]
        for rule in group["allowlist_rules"]
    }
    assert applied <= set(audit["allowlist"])
    assert "DE_MORGAN_INTEGER_GOALS_HALF_LINE_2_5" in applied
    assert "1X2_DRAW_SAME_PERIOD_BINARY_RESULT" in applied
