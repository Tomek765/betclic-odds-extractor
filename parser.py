from __future__ import annotations

import re
import unicodedata

# ─────────────────────────────────────────────────────────────────────────────
# TEAM NAME HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def clean_team_name(raw: str) -> str:
    """Remove trailing junk like trailing digits, scores, stats after team name."""
    name = raw.strip()
    name = re.sub(r"\s+\d+$", "", name).strip()
    return name


def deduplicate_owner_name(name: str) -> str:
    """Remove duplicated words in an owner/team string like 'Arsenal Arsenal'."""
    words = name.strip().split()
    if not words:
        return name
    deduped: list[str] = []
    prev = None
    for w in words:
        if w.lower() != (prev or "").lower():
            deduped.append(w)
        prev = w
    return " ".join(deduped)


def canonical_event_team_name(raw: str, home_team: str, away_team: str) -> tuple[str, str]:
    """Repair only whitespace-fragmented aliases of one explicit event participant.

    The raw source is deliberately not touched; callers use this only for canonical
    selection/owner matching.  A compact match to both participants is ambiguous.
    """
    def compact(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(char for char in text if char.isalnum())

    source = compact(raw)
    matches = [team for team in (home_team, away_team) if source and source == compact(team)]
    # Providers sometimes omit a non-distinguishing leading club token
    # (``CR Flamengo K.`` -> ``Flamengo K.``).  Accept only an unambiguous,
    # sufficiently specific suffix of an explicit event participant.  This is
    # canonical-only; callers retain RAW unchanged.
    if not matches and len(source) >= 6:
        matches = [team for team in (home_team, away_team)
                   if compact(team).endswith(source) or source.endswith(compact(team))]
    if len(matches) == 1:
        return matches[0], "EVENT_TEAM_WHITESPACE_ALIAS"
    if len(matches) > 1:
        return raw, "NAME_ALIAS_AMBIGUOUS"
    return raw, ""


def _semantic_text(value: str) -> str:
    """Accent/whitespace independent text for deterministic title rules."""
    return " ".join(unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore").decode().casefold().split())


def is_correct_score_group_selection(selection: str) -> bool:
    """Validate a closed list of three or more exact scores ("a-b, c-d lub e-f").

    Live audit 2026-09-30 showed four-score groups ("3 - 2, 4 - 2, 4 - 3 lub
    5 - 1").  A list of exact scores is fully self-describing.  Labels that
    only say "<team> - Inny wynik" or "Remis" depend on the other groups and
    are deliberately not matched.
    """
    score = r"\d+\s*-\s*\d+"
    return bool(re.fullmatch(
        rf"{score}(?:\s*,\s*{score})+\s*(?:,|lub)\s*{score}",
        str(selection or "").strip(), re.IGNORECASE,
    ))


def _column_role_from_instance(market_instance_id: str) -> str:
    match = re.search(r"\|column:([^|]+)", str(market_instance_id or ""))
    return match.group(1).replace(".", " ").strip() if match else ""


# Title of a proven Top card whose sentence matches no audited grammar.  Such a
# card is always excluded (UNRECOGNIZED_TOP_CARD), never priced or guessed.
UNRECOGNIZED_TOP_CARD_TITLE = "Karta Top - nierozpoznana treść"


def is_top_offer_card(tab_name: str, market_instance_id: str) -> bool:
    """The exact DOM boundary of a self-describing Top good-deal/offer card."""
    instance = str(market_instance_id or "").casefold()
    qa_betting_card = ("div[market-box#" in instance
                       and "bcdk-bet-button-wrapper" in instance
                       and "button[market-selection" in instance)
    return (_semantic_text(tab_name) == "top"
            and ("marketbox.is-gooddeals" in instance or qa_betting_card)
            and "sports-matrix-markets" in instance)


def recover_headerless_top_offer(selection: str, tab_name: str,
                                 market_instance_id: str, home_team: str = "",
                                 away_team: str = "") -> dict[str, str] | None:
    """Recover only audited self-describing rows in the Top good-deal matrix.

    This is deliberately not a generic missing-header fallback.  Both the exact
    DOM boundary and a complete closed row grammar are required.
    """
    if not is_top_offer_card(tab_name, market_instance_id):
        return None
    source = " ".join(str(selection or "").split())

    def exact_team(value: str) -> bool:
        return sum(bool(team) and _semantic_text(value) == _semantic_text(team)
                   for team in (home_team, away_team)) == 1

    def named_person(value: str) -> bool:
        words = _semantic_text(value).split()
        return (len(words) >= 2 and not set(words) & {"lub", "i", "oraz", "albo", "and", "or", "jego", "zmiennik", "zawodnik"}
                and bool(re.fullmatch(r"[^\W\d_][\w.'’\-]*(?:\s+[^\W\d_][\w.'’\-]*)+", value)))

    match_total = re.fullmatch(r"(Powyżej|Poniżej) (\d+(?:[.,]\d+)?) goli w meczu", source, re.IGNORECASE)
    if match_total:
        return {"market_title": "Suma goli w meczu",
                "raw_selection": f"{match_total.group(1)} {match_total.group(2)}"}
    team_total = re.fullmatch(r"(.+?) (powyżej|poniżej) (\d+(?:[.,]\d+)?) goli w meczu", source, re.IGNORECASE)
    if team_total and exact_team(team_total.group(1)):
        return {"market_title": f"{team_total.group(1)} - liczba goli w meczu",
                "raw_selection": f"{team_total.group(2)} {team_total.group(3)}"}
    substitute = re.fullmatch(r"(.+?) lub jego zmiennik strzeli gola w meczu", source, re.IGNORECASE)
    if substitute and named_person(substitute.group(1)):
        return {"market_title": "Strzelec gola lub jego zmiennik", "raw_selection": substitute.group(1)}
    # Observed live 2026-09-28 (Szwecja - Polska Top cards).
    corners_total = re.fullmatch(r"(Powyżej|Poniżej) (\d+[.,]5) rzutów rożnych w meczu", source, re.IGNORECASE)
    if corners_total:
        return {"market_title": "Rzuty rożne",
                "raw_selection": f"{corners_total.group(1)} {corners_total.group(2)}"}
    if re.fullmatch(r"Remis po pierwszej połowie meczu", source, re.IGNORECASE):
        return {"market_title": "Wynik meczu - 1. połowa", "raw_selection": "Remis"}
    corners = re.fullmatch(r"Więcej rzutów rożnych w meczu - (.+)", source, re.IGNORECASE)
    if corners and exact_team(corners.group(1)):
        return {"market_title": "Więcej rzutów rożnych", "raw_selection": corners.group(1)}
    cards = re.fullmatch(r"Więcej kartek w meczu - (.+)", source, re.IGNORECASE)
    if cards and exact_team(cards.group(1)):
        return {"market_title": "Więcej kartek", "raw_selection": cards.group(1)}
    margin = re.fullmatch(r"(.+?) wygra przewagą dokładnie ([1-9]\d*) gol(?:a|i)", source, re.IGNORECASE)
    if margin and exact_team(margin.group(1)):
        return {"market_title": "Różnica goli", "raw_selection": source}
    first_team = re.fullmatch(r"(.+?) strzeli pierwszego gola w meczu", source, re.IGNORECASE)
    if first_team and exact_team(first_team.group(1)):
        return {"market_title": "Kto zdobędzie pierwszą bramkę w meczu", "raw_selection": first_team.group(1)}
    def mentions_team(value: str) -> bool:
        text = _semantic_text(value)
        return any(team and _semantic_text(team) in text for team in (home_team, away_team))

    # Plain match outcomes in Top card wording (same closed team identity).
    match_winner = re.fullmatch(r"(.+?) wygra mecz", source, re.IGNORECASE)
    if match_winner and exact_team(match_winner.group(1)):
        return {"market_title": "Wynik meczu", "raw_selection": match_winner.group(1)}
    if re.fullmatch(r"Remis w meczu", source, re.IGNORECASE):
        return {"market_title": "Wynik meczu", "raw_selection": "Remis"}
    half_winner = re.fullmatch(r"(.+?) wygra (pierwszą|drugą) połowę meczu", source, re.IGNORECASE)
    if half_winner and exact_team(half_winner.group(1)):
        half = "1" if half_winner.group(2).casefold() == "pierwszą" else "2"
        return {"market_title": f"Wynik meczu - {half}. połowa", "raw_selection": half_winner.group(1)}
    if re.fullmatch(r"Obie drużyny strzelą gola(?: w meczu)?", source, re.IGNORECASE):
        return {"market_title": "Obie drużyny strzelą", "raw_selection": "Tak"}
    team_scores = re.fullmatch(r"(.+?) strzeli gola w meczu", source, re.IGNORECASE)
    if team_scores and exact_team(team_scores.group(1)):
        return {"market_title": f"{team_scores.group(1)} - liczba goli w meczu", "raw_selection": "Powyżej 0,5"}
    # Observed live 2026-10-02 (Francja - Wlochy Top cards), also without "(OPTA)".
    win_to_nil = re.fullmatch(r"(.+?) wygra mecz bez straty gola", source, re.IGNORECASE)
    if win_to_nil and exact_team(win_to_nil.group(1)):
        return {"market_title": f"Zwycięstwo do zera - {win_to_nil.group(1)}", "raw_selection": "Tak"}
    half_scorer = re.fullmatch(r"(.+?) strzeli gola w (pierwszej|drugiej) połowie meczu", source, re.IGNORECASE)
    if half_scorer and named_person(half_scorer.group(1)) and not mentions_team(half_scorer.group(1)):
        half = "1" if half_scorer.group(2).casefold() == "pierwszej" else "2"
        return {"market_title": f"Strzelec - {half}. połowa", "raw_selection": half_scorer.group(1)}
    match_scorer = re.fullmatch(r"(.+?) strzeli gola w meczu", source, re.IGNORECASE)
    if match_scorer and named_person(match_scorer.group(1)) and not mentions_team(match_scorer.group(1)):
        return {"market_title": "Strzelec", "raw_selection": match_scorer.group(1)}
    shots = re.fullmatch(r"(.+?) (powyżej|poniżej) (\d+(?:[.,]\d+)?) celnych strzałów na bramkę(?: \(OPTA\))?", source, re.IGNORECASE)
    if shots and named_person(shots.group(1)):
        return {"market_title": "Liczba celnych strzałów zawodnika",
                "raw_selection": f"{shots.group(2)} {shots.group(3)}", "participant_hint": shots.group(1)}
    assist_xtra = re.fullmatch(r"(.+?) zanotuje asystę - Xtra Wygrana", source, re.IGNORECASE)
    if assist_xtra and named_person(assist_xtra.group(1)):
        return {"market_title": "Zawodnik zaliczy asystę - Xtra Wygrana",
                "raw_selection": assist_xtra.group(1), "participant_hint": assist_xtra.group(1)}

    first_goal = re.fullmatch(
        r"Czas 1\. gola w meczu:\s*(\d{2}:\d{2}\s*-\s*\d{2}:\d{2})",
        source, re.IGNORECASE,
    )
    if first_goal:
        return {
            "market_title": "Czas 1. gola w meczu",
            "raw_selection": re.sub(r"\s*[-]\s*", " - ", first_goal.group(1)),
        }

    score_group = re.fullmatch(
        r"Dokładny wynik w grupie:\s*(\d+-\d+(?:,\s*\d+-\d+){2})",
        source, re.IGNORECASE,
    )
    if score_group:
        scores = ", ".join(piece.strip() for piece in score_group.group(1).split(","))
        return {"market_title": "Dokładny wynik w grupie", "raw_selection": scores}

    inline_assist = re.fullmatch(
        r"([^\W\d_][\w.'’\-]*(?:\s+[^\W\d_][\w.'’\-]*)+)\s+zanotuje\s+asystę",
        source, re.IGNORECASE,
    )
    if inline_assist:
        player = inline_assist.group(1).strip()
        return {
            "market_title": "Zawodnik zanotuje asystę",
            "raw_selection": "Over 0.5",
            "participant_hint": player,
        }
    return None


def scorer_scope_from_evidence(market_title: str, column_role: str = "") -> tuple[str, str]:
    """Return scope and proof state; never collapse an evidenced column to ANYTIME."""
    evidence = _contract_text(f"{market_title} {column_role}")
    scorer_table = _contract_text(market_title).split(" ", 1)[0] in {"strzelcy", "scorers"}
    if scorer_table and evidence.endswith(" pierwszy"):
        return "FIRST_GOAL", "PROVEN"
    if scorer_table and evidence.endswith(" ostatni"):
        return "LAST_GOAL", "PROVEN"
    if any(token in evidence for token in ("pierwszy strzelec", "first scorer", "pierwszy gol", "first goal", "1 gola", "1. gola")):
        return "FIRST_GOAL", "PROVEN"
    if any(token in evidence for token in ("ostatni strzelec", "last scorer", "ostatni gol", "last goal")):
        return "LAST_GOAL", "PROVEN"
    if "obu polowach" in evidence or "both halves" in evidence:
        return "SCORES_BOTH_HALVES", "PROVEN"
    if re.search(r"(?:^| )4\s*(?:(?:lub\s+wiecej|\+)\s*)?g(?:ol|ole|oli)\w*", evidence):
        return "FOUR_OR_MORE_GOALS", "PROVEN"
    if re.search(r"(?:^| )3\s*(?:(?:lub\s+wiecej|\+)\s*)?g(?:ol|ole|oli)\w*", evidence):
        return "THREE_OR_MORE_GOALS", "PROVEN"
    if re.search(r"(?:^| )2\s*(?:(?:lub\s+wiecej|\+)\s*)?g(?:ol|ole|oli)\w*", evidence):
        return "TWO_OR_MORE_GOALS", "PROVEN"
    if "zmiennik" in evidence or "strzelec" in evidence or "zdobedzie bramke" in evidence:
        return "ANYTIME", "PROVEN"
    return "", "COLUMN_SEMANTICS_UNRESOLVED"


def _settlement_for(family: str, line: str, handicap_kind: str = "", selection: str = "") -> str:
    """Deterministic settlement taxonomy for explicitly recognised markets."""
    if family == "DNB":
        return "PUSH_ON_DRAW"
    if family == "HALF_FULL_RESULT":
        return "WIN_LOSE" if re.fullmatch(
            r"(?:HOME|DRAW|AWAY)_(?:HOME|DRAW|AWAY)", str(selection or "")
        ) else "UNKNOWN"
    if family == "CORRECT_SCORE_GROUP":
        return "WIN_LOSE" if is_correct_score_group_selection(selection) else "UNKNOWN"
    if family == "HANDICAP_EUROPEAN":
        if handicap_kind == "THREE_WAY":
            return "WIN_DRAW_LOSE"
        if handicap_kind == "TWO_WAY":
            try:
                return "PUSH_POSSIBLE" if float(line).is_integer() else "NO_PUSH"
            except ValueError:
                return "UNKNOWN"
    if family in _KNOWN_NOT_MODELED_FAMILIES:
        return _known_not_modeled_settlement(family, selection)
    resolved = {
        "1X2", "DOUBLE_CHANCE", "BTTS", "GOALS_OU", "TEAM_TOTALS_HOME",
        "TEAM_TOTALS_AWAY", "GOALSCORER", "PLAYER_PROP", "CORRECT_SCORE",
        "RESULT_AND_GOALS", "FIRST_GOAL_TEAM", "LAST_GOAL_TEAM", "NO_GOAL",
        "PENALTY_GOAL", "PLAYER_COMBINATION", "EARLY_WIN_OR_TWO_GOAL_LEAD",
        "COMPOUND_LOGIC",
    }
    if family == "EVENT_TOTAL":
        try:
            return "PUSH_POSSIBLE" if float(line).is_integer() else "NO_PUSH"
        except ValueError:
            return "UNKNOWN"
    if family in resolved:
        if family in {"GOALS_OU", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY"}:
            try:
                return "PUSH_POSSIBLE" if float(line).is_integer() else "NO_PUSH"
            except ValueError:
                return "UNKNOWN"
        return "WIN_LOSE"
    return "UNKNOWN"


_KNOWN_NOT_MODELED_FAMILIES = {
    "GOAL_PARITY", "CLEAN_SHEET", "TEAM_WIN_TO_NIL", "EXACT_GOALS", "GOAL_RANGE",
    "HIGHER_SCORING_HALF", "GOAL_MARGIN", "TEAM_SCORES_BOTH_HALVES",
    "TEAM_WINS_ONE_HALF", "TEAM_WINS_BOTH_HALVES", "FIRST_GOAL_TIME",
    "QUALIFICATION_WINNER", "QUALIFICATION_METHOD", "BINARY_EVENT",
    "EVENT_FIRST_LAST", "EVENT_RANGE", "EVENT_PARITY", "EVENT_EXACT", "EVENT_RESULT",
}


def _known_not_modeled_settlement(family: str, selection: str) -> str:
    """Prove outcome shape for narrow, standard markets outside the pricing model."""
    value = _semantic_text(str(selection or "").replace("ł", "l").replace("Ł", "L"))
    if family == "GOAL_PARITY":
        return "WIN_LOSE" if value in {"parzyste", "nieparzyste", "even", "odd"} else "UNKNOWN"
    if family in {"CLEAN_SHEET", "TEAM_WIN_TO_NIL", "TEAM_SCORES_BOTH_HALVES", "TEAM_WINS_ONE_HALF", "TEAM_WINS_BOTH_HALVES"}:
        return "WIN_LOSE" if value in {"tak", "nie", "yes", "no"} else "UNKNOWN"
    if family == "EXACT_GOALS":
        return "WIN_LOSE" if re.fullmatch(r"\d+\+?", value) else "UNKNOWN"
    if family == "GOAL_RANGE":
        # "Brak Gola" is the explicit zero-goals option of the same range market.
        return "WIN_LOSE" if value == "brak gola" or re.fullmatch(r"\d+\+?(?:\s*-\s*\d+\+?)?", value) else "UNKNOWN"
    if family == "HIGHER_SCORING_HALF":
        return "WIN_LOSE" if value in {"remis", "draw"} or bool(re.fullmatch(r"[12]\.?\s+polowa", value)) else "UNKNOWN"
    if family == "GOAL_MARGIN":
        return "WIN_LOSE" if value == "remis" or ("przewaga" in value and bool(re.search(r"\d", value))) else "UNKNOWN"
    if family == "FIRST_GOAL_TIME":
        # Windows end at a clock time, at the break, or at the stated end of
        # regular time; "Przerwa - 59:59" mirrors the accepted "30:00 - Przerwa".
        # "Brak Gola" is the explicit no-goal option.
        return "WIN_LOSE" if value == "brak gola" or re.fullmatch(
            r"\d{2}:\d{2}\s*-\s*(?:\d{2}:\d{2}|przerwa|koniec meczu \(90\s*min\))|przerwa\s*-\s*\d{2}:\d{2}",
            value) else "UNKNOWN"
    if family == "QUALIFICATION_WINNER":
        return "WIN_LOSE" if value else "UNKNOWN"
    if family == "QUALIFICATION_METHOD":
        return "WIN_LOSE" if value and any(token in value for token in ("90 min", "dogryw", "karn")) else "UNKNOWN"
    if family == "BINARY_EVENT":
        return "WIN_LOSE" if value in {"tak", "nie", "yes", "no"} else "UNKNOWN"
    if family == "EVENT_FIRST_LAST":
        return "WIN_LOSE" if value else "UNKNOWN"
    if family in {"EVENT_RANGE", "EVENT_EXACT"}:
        return "WIN_LOSE" if re.fullmatch(r"\d+(?:\+|\s*-\s*\d+\+?)?", value) else "UNKNOWN"
    if family == "EVENT_PARITY":
        return "WIN_LOSE" if value in {"parzyste", "nieparzyste", "even", "odd"} else "UNKNOWN"
    if family == "EVENT_RESULT":
        return "WIN_DRAW_LOSE" if value in {"home", "away", "draw"} else "UNKNOWN"
    return "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# FAMILY / PERIOD / LINE CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

_PLAYER_OFFSIDES_SINGLE_MARKET_TITLES = frozenset({
    "liczba spalonych zawodnika (opta)",
    "liczba spalonych zawodnika (opta) - 1. polowa",
    "liczba spalonych zawodnika (supersub)",
})

_PLAYER_CARDS_SINGLE_MARKET_TITLES = frozenset({
    "liczba kartek zawodnika",
    "liczba kartek zawodnika - 1. polowa",
    "liczba kartek zawodnika (supersub)",
})

_PLAYER_ASSIST_THRESHOLD_MARKET_TITLES = frozenset({
    "zawodnik zanotuje asyste",
    "zawodnik asystujacy + jego zmiennik",
})

_PLAYER_ASSIST_RESULT_MARKET_TITLE = "zawodnik zaliczy asyste"

_EXACT_BINARY_MATCH_EVENT_TITLES = frozenset({
    "sedzia sprawdzi sytuacje na var (podejdzie do monitora)",
    "bramka rezerwowego",
    "hat-trick",
    "gol glowa",
    "gol glowa - 1. polowa",
    "gol glowa - 2. polowa",
    "gol bezposrednio z rzutu wolnego w meczu",
})

_EXACT_COMPOUND_MATCH_EVENT_TITLES = frozenset({
    "gole glowa w obu polowach",
    "obie druzyny strzela gola glowa",
    "obie druzyny strzela gola z rzutu wolnego",
})

_EXACT_SPECIALTIES_REQUIRING_TIME_EVIDENCE = frozenset({
    "sedzia sprawdzi sytuacje na var (podejdzie do monitora)",
    "bramka rezerwowego",
    "hat-trick",
    "gol glowa",
    "gole",
    "obie druzyny strzela gola glowa",
    "obie druzyny strzela gola z rzutu wolnego",
})


def _contract_text(value: str) -> str:
    return _semantic_text(str(value or "").replace("ł", "l").replace("Ł", "L"))


def _is_audited_event_total_title(market_title: str, home_team: str,
                                  away_team: str) -> bool:
    title = _contract_text(market_title)
    if title in {
        "rzuty rozne", "liczba kartek", "liczba strzalow w meczu (opta)",
        "liczba celnych strzalow w meczu (opta)",
        "liczba fauli w meczu (opta) (z dogrywka)",
        "liczba odbiorow (opta) (z dogrywka)",
        "liczba spalonych w meczu (opta)",
        "1. polowa - rzuty rozne", "liczba kartek 1. polowa",
        "suma rzutow roznych (razem z dogrywka)",
        "punkty za kartki powyzej/ponizej",
        "punkty za kartki powyzej/ponizej - 1. polowa",
    }:
        return True
    for team in filter(None, (_contract_text(home_team), _contract_text(away_team))):
        if title in {
            f"liczba strzalow w meczu (opta) - {team}",
            f"liczba celnych strzalow w meczu (opta) - {team}",
            f"liczba fauli (opta) - {team} (z dogrywka)",
            f"liczba odbiorow (opta) (z dogrywka) - {team}",
            f"liczba spalonych w meczu - {team} (opta)",
            f"rzuty rozne (bez dogrywki) - {team}",
            f"rzuty rozne {team} (razem z dogrywka)",
            f"kartki - {team}",
        }:
            return True
    return False


def _audited_event_contract_requires_time_evidence(
    market_title: str, home_team: str, away_team: str,
) -> bool:
    """Closed titles whose outcome is proven but duration is not."""
    title = _contract_text(market_title)
    if title in {
        "rzuty rozne", "liczba kartek", "wiecej rzutow roznych",
        "wiecej kartek", "pierwszy strzal", "pierwszy celny strzal",
        "pierwszy zespol ktory otrzyma kartke", "dokladna liczba kartek",
        "pierwsza druzyna, ktora popelni faul",
        "punkty za kartki powyzej/ponizej", "czerwona kartka",
    }:
        return True
    for team in filter(None, (_contract_text(home_team), _contract_text(away_team))):
        if title in {f"kartki - {team}", f"dokladna liczba kartek - {team}", f"czerwona kartka - {team}"}:
            return True
    return False

_SCORER_ASSISTER_REGULAR_TIME_TITLE = (
    "strzelec bramki i zawodnik, ktory zaliczy przy niej asyste (czas reg.)"
)

_PLAYER_GOAL_ASSIST_BASE_OR_TITLE = "zawodnik strzeli gola lub zaliczy asyste"
_PLAYER_GOAL_ASSIST_SUPERSUB_OR_TITLE = _PLAYER_GOAL_ASSIST_BASE_OR_TITLE + " + jego zmiennik"
_PLAYER_GOAL_ASSIST_BASE_AND_TITLE = "zawodnik strzeli gola i zaliczy asyste"
_PLAYER_GOAL_ASSIST_SUPERSUB_AND_TITLE = "zawodnik lub jego zmiennik strzeli gola i zaliczy asyste"
_PLAYER_GOAL_ASSIST_XTRA_TITLE = _PLAYER_GOAL_ASSIST_BASE_OR_TITLE + " - xtra wygrana"
_PLAYER_GOAL_ASSIST_SINGLE_TITLES = frozenset({
    _PLAYER_GOAL_ASSIST_BASE_OR_TITLE,
    _PLAYER_GOAL_ASSIST_SUPERSUB_OR_TITLE,
    _PLAYER_GOAL_ASSIST_BASE_AND_TITLE,
    _PLAYER_GOAL_ASSIST_SUPERSUB_AND_TITLE,
})
_PLAYER_GOAL_ASSIST_COMBINATION_TITLES = {
    "ktorykolwiek zawodnik strzeli gola lub zaliczy asyste": "ANY_GOAL_OR_ASSIST",
    "obaj gracze strzela gola lub zalicza asyste": "ALL_GOAL_OR_ASSIST",
}
_PLAYER_ASSIST_COMBINATION_TITLES = {
    "ktorykolwiek zawodnik zaliczy asyste": "ANY_ASSIST",
    "ktorykolwiek zawodnik zaliczy asyste - 3 zawodnikow": "ANY_ASSIST_THREE_PLAYERS",
}
_PLAYER_ASSIST_XTRA_TITLE = "zawodnik zaliczy asyste - xtra wygrana"
_PLAYER_PENALTY_CONVERSION_TITLE = "zawodnik wykorzysta rzut karny."


def _is_player_offsides_single_market_title(market_title: str) -> bool:
    """Match only the audited inline-player offsides template."""
    semantic_title = _semantic_text(str(market_title).replace("ł", "l").replace("Ł", "L"))
    return semantic_title in _PLAYER_OFFSIDES_SINGLE_MARKET_TITLES


def _is_inline_player_ou_single_market_title(market_title: str) -> bool:
    """Match only audited rows that co-locate player, O/U and line."""
    semantic_title = _semantic_text(str(market_title).replace("ł", "l").replace("Ł", "L"))
    return (semantic_title in _PLAYER_OFFSIDES_SINGLE_MARKET_TITLES or
            semantic_title in _PLAYER_CARDS_SINGLE_MARKET_TITLES)


def _is_player_assist_threshold_market_title(market_title: str) -> bool:
    """Match only the two audited grouped assist-threshold templates."""
    return _semantic_text(market_title) in _PLAYER_ASSIST_THRESHOLD_MARKET_TITLES


def _player_score_and_total_line(market_title: str) -> str:
    """Return the total only for the audited player-score AND half-total title."""
    match = re.fullmatch(
        r"zawodnik strzeli i powyzej ([0-9]+(?:[,.][0-9]+)?) gol(?:a|e|i) - [12]\. po(?:l)?owa",
        _semantic_text(market_title),
    )
    return match.group(1).replace(",", ".") if match else ""


def _assist_threshold_line(market_title: str, column_heading: str) -> str:
    """Translate an exact audited assist column into its equivalent O/U line."""
    title = _semantic_text(market_title)
    heading = _semantic_text(column_heading)
    if title == "zawodnik zanotuje asyste":
        return {"1 +": "0.5", "2 +": "1.5"}.get(heading, "")
    if title == "zawodnik asystujacy + jego zmiennik":
        return {
            "1 asysta lub wiecej": "0.5",
            "2 asysty lub wiecej": "1.5",
        }.get(heading, "")
    return ""


def _assist_result_condition(market_title: str, column_heading: str) -> str:
    """Return a compound predicate only for the audited assist/result table."""
    if _semantic_text(market_title) != _PLAYER_ASSIST_RESULT_MARKET_TITLE:
        return ""
    heading = _semantic_text(str(column_heading).replace("ł", "l").replace("Ł", "L"))
    return {
        "i jego zespol wygra": "ASSIST_AND_TEAM_WIN",
        "i jego zespol zremisuje": "ASSIST_AND_TEAM_DRAW",
        "i zespol przegra": "ASSIST_AND_TEAM_LOSS",
    }.get(heading, "")


def _is_scorer_assister_regular_time_title(market_title: str) -> bool:
    return _semantic_text(market_title) == _SCORER_ASSISTER_REGULAR_TIME_TITLE


def _goal_assist_single_kind(market_title: str) -> str:
    title = _semantic_text(market_title)
    if title == _PLAYER_GOAL_ASSIST_XTRA_TITLE:
        return "XTRA_OR"
    if title in {_PLAYER_GOAL_ASSIST_BASE_AND_TITLE, _PLAYER_GOAL_ASSIST_SUPERSUB_AND_TITLE}:
        return "AND"
    if title in {_PLAYER_GOAL_ASSIST_BASE_OR_TITLE, _PLAYER_GOAL_ASSIST_SUPERSUB_OR_TITLE}:
        return "OR"
    return ""


def _goal_assist_combination_mode(market_title: str) -> str:
    return _PLAYER_GOAL_ASSIST_COMBINATION_TITLES.get(_semantic_text(market_title), "")


def _goal_assist_threshold_line(market_title: str, column_heading: str) -> str:
    title = _semantic_text(market_title)
    heading = _semantic_text(column_heading)
    if title == _PLAYER_GOAL_ASSIST_BASE_OR_TITLE:
        return {"1 +": "0.5", "2 +": "1.5", "3 +": "2.5"}.get(heading, "")
    if title == _PLAYER_GOAL_ASSIST_SUPERSUB_OR_TITLE:
        return {
            "1x lub wiecej": "0.5",
            "2x lub wiecej": "1.5",
            "3x lub wiecej": "2.5",
        }.get(heading, "")
    return ""


def _goal_assist_result_condition(market_title: str, column_heading: str) -> str:
    if _semantic_text(market_title) != _PLAYER_GOAL_ASSIST_BASE_OR_TITLE:
        return ""
    heading = _semantic_text(str(column_heading).replace("ł", "l").replace("Ł", "L"))
    return {
        "i jego zespol wygra": "GOAL_OR_ASSIST_AND_TEAM_WIN",
        "i jego zespol zremisuje": "GOAL_OR_ASSIST_AND_TEAM_DRAW",
        "i zespol przegra": "GOAL_OR_ASSIST_AND_TEAM_LOSS",
    }.get(heading, "")


def _pure_assist_combination_mode(market_title: str) -> str:
    return _PLAYER_ASSIST_COMBINATION_TITLES.get(_semantic_text(market_title), "")


def _is_pure_assist_xtra_title(market_title: str) -> bool:
    return _semantic_text(market_title) == _PLAYER_ASSIST_XTRA_TITLE


def _is_player_penalty_conversion_title(market_title: str) -> bool:
    return _semantic_text(market_title) == _PLAYER_PENALTY_CONVERSION_TITLE


def _player_goal_combination_contract(market_title: str,
                                      selection: str = "") -> dict[str, str | int] | None:
    """Closed multi-player scorer templates with delimiter/count firewalls."""
    if _goal_assist_combination_mode(market_title):
        # These exact titles share a scorer prefix but their assist alternative
        # is settlement-material and must remain in the goal/assist contract.
        return None
    title = _contract_text(market_title)
    contract: dict[str, str | int] | None = None
    if title.startswith("ktorykolwiek zawodnik strzeli gola"):
        count = 3 if "3 graczy" in title or "(3 pl)" in title else 2
        contract = {"mode": "ANY_PLAYER_SCORES", "scope": "ANYTIME",
                    "delimiter": "/", "count": count, "line": ""}
    elif title == "ktorykolwiek zawodnik lub jego zmiennik strzeli gola":
        contract = {"mode": "ANY_PLAYER_OR_SUBSTITUTE_SCORES",
                    "scope": "ANYTIME_SUPERSUB", "delimiter": "/", "count": 2, "line": ""}
    elif title.startswith("ktorykolwiek z graczy strzeli 2 gole lub wiecej"):
        count = 3 if "3 graczy" in title else 2
        contract = {"mode": "ANY_PLAYER_SCORES_TWO_PLUS",
                    "scope": "TWO_OR_MORE_GOALS", "delimiter": "/", "count": count, "line": ""}
    elif title.startswith("ktorykolwiek z graczy strzeli 3 gole lub wiecej"):
        count = 3 if "3 graczy" in title else 2
        contract = {"mode": "ANY_PLAYER_SCORES_THREE_PLUS",
                    "scope": "THREE_OR_MORE_GOALS", "delimiter": "/", "count": count, "line": ""}
    elif title == "jeden z graczy strzeli pierwszego gola":
        contract = {"mode": "ANY_PLAYER_FIRST_GOAL", "scope": "FIRST_GOAL",
                    "delimiter": "/", "count": 2, "line": ""}
    elif title == "jeden z graczy strzeli w obu polowach":
        contract = {"mode": "ANY_PLAYER_SCORES_BOTH_HALVES", "scope": "SCORES_BOTH_HALVES",
                    "delimiter": "/", "count": 2, "line": ""}
    elif title == "ktorykolwiek gracz zdobedzie gola w obu polowach":
        contract = {"mode": "ANY_PLAYER_SCORES_BOTH_HALVES", "scope": "SCORES_BOTH_HALVES",
                    "delimiter": "/", "count": 3, "line": ""}
    elif title in {
        "obaj gracze strzela",
        "obaj gracze strzela w 1. polowa",
        "obaj gracze strzela w 2. polowa",
    }:
        contract = {"mode": "ALL_PLAYERS_SCORE", "scope": "ANYTIME",
                    "delimiter": "&", "count": 2, "line": ""}
    elif title == "wszyscy strzela":
        contract = {"mode": "ALL_PLAYERS_SCORE", "scope": "ANYTIME",
                    "delimiter": "&", "count": 3, "line": ""}
    elif title == "obaj gracze strzela w obu polowach":
        contract = {"mode": "ALL_PLAYERS_SCORE_BOTH_HALVES",
                    "scope": "ALL_SCORE_BOTH_HALVES", "delimiter": "&",
                    "count": 2, "line": ""}
    elif title == "obaj gracze lub ich zmiennicy strzela gola":
        contract = {"mode": "ALL_PLAYERS_OR_SUBSTITUTES_SCORE",
                    "scope": "ANYTIME_SUPERSUB", "delimiter": "&", "count": 2, "line": ""}
    else:
        combined = re.fullmatch(
            r"([23]) graczy strzeli pow\. ([0-9]+(?:[,.][0-9]+)?) gole", title,
        )
        if combined:
            contract = {"mode": "SELECTED_PLAYERS_COMBINED_GOALS_OVER", "scope": "",
                        "delimiter": "&", "count": int(combined.group(1)),
                        "line": combined.group(2).replace(",", ".")}
    if contract is None or not selection:
        return contract
    delimiter = str(contract["delimiter"])
    pieces = [piece.strip() for piece in selection.split(delimiter) if piece.strip()]
    return contract if len(pieces) == int(contract["count"]) else None


def _scorer_result_condition(market_title: str, column_heading: str) -> str:
    title, heading = _contract_text(market_title), _contract_text(column_heading)
    if title == "strzelcy":
        return {
            "i jego zespol wygra": "SCORER_AND_TEAM_WIN",
            "i jego zespo wygra": "SCORER_AND_TEAM_WIN",
            "i jego zespol zremisuje": "SCORER_AND_TEAM_DRAW",
            "i jego zespo zremisuje": "SCORER_AND_TEAM_DRAW",
            "i zespol przegra": "SCORER_AND_TEAM_LOSS",
            "i zespo przegra": "SCORER_AND_TEAM_LOSS",
        }.get(heading, "")
    if title == "strzelec gola lub jego zmiennik":
        return {
            "jego druzyna wygra": "SCORER_OR_SUBSTITUTE_AND_TEAM_WIN",
            "& jego druzyna wygra": "SCORER_OR_SUBSTITUTE_AND_TEAM_WIN",
            "& jego druyna wygra": "SCORER_OR_SUBSTITUTE_AND_TEAM_WIN",
            "jego druzyna zremisuje": "SCORER_OR_SUBSTITUTE_AND_TEAM_DRAW",
            "& jego druzyna zremisuje": "SCORER_OR_SUBSTITUTE_AND_TEAM_DRAW",
            "& jego druyna zremisuje": "SCORER_OR_SUBSTITUTE_AND_TEAM_DRAW",
            "jego druzyna przegra": "SCORER_OR_SUBSTITUTE_AND_TEAM_LOSS",
            "& jego druzyna przegra": "SCORER_OR_SUBSTITUTE_AND_TEAM_LOSS",
            "& jego druyna przegra": "SCORER_OR_SUBSTITUTE_AND_TEAM_LOSS",
        }.get(heading, "")
    return ""


def _scorer_substitute_threshold(market_title: str,
                                 column_heading: str) -> tuple[str, str]:
    if _contract_text(market_title) != "strzelec i jego zmiennik":
        return "", ""
    return {
        "2 lub wiecej": ("SCORER_AND_SUBSTITUTE_TWO_PLUS", "TWO_OR_MORE_GOALS"),
        "3 lub wiecej": ("SCORER_AND_SUBSTITUTE_THREE_PLUS", "THREE_OR_MORE_GOALS"),
    }.get(_contract_text(column_heading), ("", ""))


def _is_player_outscores_opponent_title(market_title: str) -> bool:
    return _contract_text(market_title) == (
        "zawodnik strzeli wiecej goli niz druzyna przeciwna (90 min)"
    )


def _is_exact_match_compound_title(market_title: str) -> bool:
    """Closed fixture-backed match compounds which broad families cannot model."""
    title = _contract_text(market_title)
    if re.fullmatch(
        r"obie polowy (?:powyzej|ponizej) [0-9]+(?:[,.][0-9]+)? gol(?:a|e|i)",
        title,
    ):
        return True
    if re.fullmatch(
        r"oba zespoly strzela gola lub (?:powyzej|ponizej) "
        r"[0-9]+(?:[,.][0-9]+)? gola w meczu",
        title,
    ):
        return True
    return title in {
        "oba zespoly strzela w 1. i 2. polowie",
        "obie druzyny strzela po 2+",
        "podwojna szansa & oba zespoly strzela",
        "podwojna szansa & powyzej/ponizej",
        "podwojna szansa, obie druzyny zdobywaja gole - 1. polowa",
        "podwojna szansa (1.polowa lub mecz)",
        "wynik i kto zdobedzie 1. bramke",
        "oba zespoly strzela gola / liczba bramek",
    }


def _match_compound_contract(market_title: str, raw_selection: str,
                             home_team: str, away_team: str) -> dict[str, str] | None:
    """Return a lossless predicate tag only for audited, exact outcome shapes."""
    title, selected = _contract_text(market_title), _contract_text(raw_selection)
    yes_no = {"tak": "YES", "yes": "YES", "nie": "NO", "no": "NO"}

    both_halves = re.fullmatch(
        r"obie polowy (powyzej|ponizej) ([0-9]+(?:[,.][0-9]+)?) gol(?:a|e|i)",
        title,
    )
    if both_halves and selected in yes_no:
        direction = "OVER" if both_halves.group(1) == "powyzej" else "UNDER"
        return {"selection": f"BOTH_HALVES_{direction}_{yes_no[selected]}",
                "line": both_halves.group(2).replace(",", ".")}

    if title == "oba zespoly strzela w 1. i 2. polowie":
        components = [yes_no.get(piece.strip(), "") for piece in selected.split("/")]
        if len(components) == 2 and all(components):
            return {"selection": f"BTTS_H1_{components[0]}_H2_{components[1]}", "line": ""}

    if title == "obie druzyny strzela po 2+" and selected in yes_no:
        return {"selection": f"BOTH_TEAMS_AT_LEAST_TWO_{yes_no[selected]}", "line": "2"}

    dc_titles = {
        "podwojna szansa & oba zespoly strzela": "BTTS",
        "podwojna szansa, obie druzyny zdobywaja gole - 1. polowa": "BTTS",
        "podwojna szansa & powyzej/ponizej": "TOTAL",
    }
    if title in dc_titles and "&" in raw_selection:
        dc_raw, condition_raw = [piece.strip() for piece in raw_selection.split("&", 1)]
        dc = {"1X": "HOME_DRAW", "12": "HOME_AWAY", "X2": "AWAY_DRAW"}.get(
            _classify_double_chance_selection(dc_raw, home_team, away_team), "",
        )
        condition = _contract_text(condition_raw)
        if dc and dc_titles[title] == "BTTS" and condition in yes_no:
            return {"selection": f"DC_{dc}_AND_BTTS_{yes_no[condition]}", "line": ""}
        total = re.fullmatch(r"(powyzej|ponizej) ([0-9]+(?:[,.][0-9]+)?)", condition)
        if dc and dc_titles[title] == "TOTAL" and total:
            direction = "OVER" if total.group(1) == "powyzej" else "UNDER"
            return {"selection": f"DC_{dc}_AND_{direction}",
                    "line": total.group(2).replace(",", ".")}

    if title == "podwojna szansa (1.polowa lub mecz)":
        side = _classify_selection_side(raw_selection, home_team, away_team)
        if side in {"HOME", "DRAW", "AWAY"}:
            return {"selection": f"{side}_RESULT_OCCURS_1H_OR_FT", "line": ""}

    if title == "wynik i kto zdobedzie 1. bramke" and "/" in raw_selection:
        result_raw, first_raw = [piece.strip() for piece in raw_selection.split("/", 1)]
        result_side = _classify_selection_side(result_raw, home_team, away_team)
        first_side = _classify_selection_side(
            re.sub(r"\s+strzeli\s+pierwszy\s*$", "", first_raw, flags=re.IGNORECASE),
            home_team, away_team,
        )
        if result_side in {"HOME", "DRAW", "AWAY"} and first_side in {"HOME", "AWAY"}:
            return {"selection": f"{result_side}_RESULT_AND_{first_side}_FIRST", "line": ""}

    btts_or_total = re.fullmatch(
        r"oba zespoly strzela gola lub (powyzej|ponizej) "
        r"([0-9]+(?:[,.][0-9]+)?) gola w meczu",
        title,
    )
    if btts_or_total and selected in yes_no:
        direction = "OVER" if btts_or_total.group(1) == "powyzej" else "UNDER"
        return {"selection": f"BTTS_OR_{direction}_{yes_no[selected]}",
                "line": btts_or_total.group(2).replace(",", ".")}

    if title == "oba zespoly strzela gola / liczba bramek":
        combined = re.fullmatch(
            r"(tak|nie|yes|no) i (powyzej|ponizej|over|under) "
            r"([0-9]+(?:[,.][0-9]+)?)",
            selected,
        )
        if combined:
            btts = yes_no[combined.group(1)]
            direction = "OVER" if combined.group(2) in {"powyzej", "over"} else "UNDER"
            return {"selection": f"BTTS_{btts}_AND_{direction}",
                    "line": combined.group(3).replace(",", ".")}
    return None


def classify_family(market_title: str, selection: str, section_title: str,
                    home_team: str, away_team: str) -> tuple[str, str]:
    """
    Returns (FAMILY, OWNER).
    OWNER: "" for generic markets, team name for team-specific, player name for player props.
    """
    tl = market_title.lower()
    semantic_title = _semantic_text(str(market_title).replace("ł", "l").replace("Ł", "L"))
    semantic_selection = _semantic_text(str(selection).replace("ł", "l").replace("Ł", "L"))

    def explicit_team_owner() -> str:
        matches = [team for team in (home_team, away_team)
                   if _semantic_text(str(team).replace("ł", "l").replace("Ł", "L")) and
                   _semantic_text(str(team).replace("ł", "l").replace("Ł", "L")) in semantic_title]
        return matches[0] if len(matches) == 1 else ""

    if _is_exact_match_compound_title(market_title):
        return "COMPOUND_LOGIC", ""
    if semantic_title == "zwyciestwo do zera" and semantic_selection in {
        "tak", "nie", "yes", "no",
    }:
        return "TEAM_WIN_TO_NIL", ""
    # Recovered Top card "<team> wygra mecz bez straty gola" names its team.
    if semantic_title.startswith("zwyciestwo do zera - ") and semantic_selection in {"tak", "nie", "yes", "no"}:
        owner = explicit_team_owner()
        if owner:
            return "TEAM_WIN_TO_NIL", owner

    # Result + BTTS is a known, binary compound proposition.  It is not used by
    # the pricing model, but the title itself proves its settlement domain, so
    # preserve it losslessly as COMPOUND_LOGIC rather than mislabelling it as an
    # unknown settlement.  Other specialist BTTS propositions stay fail-closed
    # below unless their distinct outcome shape is explicitly recognised.
    if ("wynik/" in semantic_title or "wynik i oba" in semantic_title or
            ("wynik" in semantic_title and "oba zesp" in semantic_title and "strzela" in semantic_title)):
        return "COMPOUND_LOGIC", ""
    # Closed, standard propositions outside the valuation model.  The event
    # type stays losslessly in MARKET; the family specifies the payout shape.
    if "zwyciezca rywalizacji" in semantic_title or "winner of tie" in semantic_title:
        return "QUALIFICATION_WINNER", ""
    if "sposob awansu" in semantic_title or "method of qualification" in semantic_title:
        return "QUALIFICATION_METHOD", ""
    if (any(token in semantic_title for token in ("dogrywka", "seria rzutow karnych", "penalties")) and
            any(token in semantic_title for token in ("tak/nie", "yes/no"))):
        return "BINARY_EVENT", ""
    if (semantic_title in _EXACT_BINARY_MATCH_EVENT_TITLES
            and semantic_selection in {"tak", "nie", "yes", "no"}):
        return "BINARY_EVENT", ""
    # This exact team proposition must precede the broad goals-total rules.
    if semantic_selection in {"tak", "nie", "yes", "no"}:
        owners = [team for team in (home_team, away_team) if team and semantic_title ==
                  "strzela gola bezposrednio z rzutu wolnego - " + _semantic_text(team)]
        if len(owners) == 1:
            return "BINARY_EVENT", owners[0]
        # Red card in the match / for one named team (live 2026-10-02,
        # Wegry - Gruzja, Statystyki tab): a closed Tak/Nie outcome shape.  Its
        # duration is not documented, so the period stays unresolved.
        card_title = _semantic_text(str(market_title).replace("ł", "l").replace("Ł", "L"))
        if card_title == "czerwona kartka":
            return "BINARY_EVENT", ""
        owners = [team for team in (home_team, away_team) if team and card_title ==
                  "czerwona kartka - " + _semantic_text(str(team).replace("ł", "l").replace("Ł", "L"))]
        if len(owners) == 1:
            return "BINARY_EVENT", owners[0]
    if (semantic_title in _EXACT_COMPOUND_MATCH_EVENT_TITLES
            and semantic_selection in {"tak", "nie", "yes", "no"}):
        return "COMPOUND_LOGIC", ""
    if (semantic_title == "gole"
            and re.fullmatch(r"(?:powyzej|ponizej|over|under)\s+\d+(?:[,.]\d+)?", semantic_selection)):
        return "GOALS_OU", ""
    numeric_ou = bool(re.fullmatch(
        r"(?:powyzej|ponizej|over|under)\s+\d+(?:[,.]\d+)?", semantic_selection,
    ))
    if numeric_ou and _is_audited_event_total_title(market_title, home_team, away_team):
        return "EVENT_TOTAL", explicit_team_owner()

    numeric_bucket = bool(re.fullmatch(r"\d+\+?(?:\s*-\s*\d+\+?)?", semantic_selection))
    event_exact_titles = {"liczba kartek - 1. polowa", "dokladna liczba kartek"}
    for team in filter(None, (_contract_text(home_team), _contract_text(away_team))):
        event_exact_titles.update({
            f"{team} dokladna liczba kartek - 1. polowa",
            f"dokladna liczba kartek - {team}",
        })
    if numeric_bucket and semantic_title in event_exact_titles:
        return "EVENT_EXACT", explicit_team_owner()

    event_first_titles = {
        "pierwsza kartka- 1. polowa",
        "pierwsza druzyna, ktora zostanie zlapana na pozycji spalonej w meczu",
        "pierwszy strzal", "pierwszy celny strzal",
        "pierwszy zespol ktory otrzyma kartke",
        "pierwsza druzyna, ktora popelni faul",
    }
    event_sides = {_contract_text(home_team), _contract_text(away_team),
                   "nikt", "bez kartek"}
    if semantic_title in event_first_titles and semantic_selection in event_sides:
        selected_owner = (home_team if semantic_selection == _contract_text(home_team) else
                          away_team if semantic_selection == _contract_text(away_team) else "")
        return "EVENT_FIRST_LAST", selected_owner

    if (semantic_title in {"wiecej rzutow roznych", "wiecej kartek"}
            and semantic_selection in {_contract_text(home_team), _contract_text(away_team),
                                       "remis", "draw"}):
        selected_owner = (home_team if semantic_selection == _contract_text(home_team) else
                          away_team if semantic_selection == _contract_text(away_team) else "")
        return "EVENT_RESULT", selected_owner
    # A capture may replace the accented word "rożne"; the "rzut" stem is
    # still sufficient here because this branch only describes event markets.
    is_corner = any(token in semantic_title for token in ("rzut", "corners", "rozne", "rozny", "rone", "rony"))
    if is_corner and any(token in semantic_title for token in ("pierwszy", "ostatni", "nastepny", "first", "last", "next")):
        return "EVENT_FIRST_LAST", ""
    if is_corner and any(token in semantic_title for token in ("przedzial", "range")):
        return "EVENT_RANGE", explicit_team_owner()
    if is_corner and any(token in semantic_title for token in ("nieparz", "parzyst", "parity")):
        return "EVENT_PARITY", explicit_team_owner()
    if is_corner and any(token in semantic_title for token in ("dokladna liczba", "exact number")):
        return ("EVENT_RANGE" if re.fullmatch(r"\d+(?:\+|\s*-\s*\d+\+?)?", _semantic_text(selection)) else "EVENT_EXACT"), explicit_team_owner()
    if is_corner and re.fullmatch(r"\d+(?:\+|\s*-\s*\d+\+?)?", _semantic_text(selection)):
        return "EVENT_RANGE", explicit_team_owner()
    if is_corner and any(token in semantic_title for token in (" w- ", "winner", "zwyciezca")):
        selection_key = _semantic_text(selection)
        if selection_key == _semantic_text(home_team):
            return "EVENT_RESULT", home_team
        if selection_key == _semantic_text(away_team):
            return "EVENT_RESULT", away_team
        if selection_key in {"remis", "draw"}:
            return "EVENT_RESULT", ""
    if ("parzyst" in semantic_title or "nieparzyst" in semantic_title) and (
            "liczba goli" in semantic_title or "gole" in semantic_title):
        return "GOAL_PARITY", explicit_team_owner()
    if "czas" in semantic_title and re.search(r"(?:^|\s)1\.?\s*gola(?:\s|$)|pierwsz(?:ego)?\s*gola", semantic_title):
        return "FIRST_GOAL_TIME", ""
    if "czyste konto" in semantic_title or "bez utraty bramki" in semantic_title:
        return "CLEAN_SHEET", explicit_team_owner()
    if "dokladna liczba" in semantic_title and ("goli" in semantic_title or "bramek" in semantic_title):
        return "EXACT_GOALS", explicit_team_owner()
    if "liczba goli - opcja" in semantic_title or (
            "liczba goli" in semantic_title and (
                re.fullmatch(r"\d+\+?(?:\s*-\s*\d+\+?)?", semantic_selection) or semantic_selection == "brak gola")):
        return "GOAL_RANGE", explicit_team_owner()
    if "polowa z wieksza" in semantic_title and ("liczba goli" in semantic_title or "iloscia goli" in semantic_title):
        return "HIGHER_SCORING_HALF", explicit_team_owner()
    if "roznica goli" in semantic_title and ("przewaga" in semantic_selection or semantic_selection == "remis"):
        return "GOAL_MARGIN", ""
    if "strzela w obu polowach" in semantic_title and explicit_team_owner():
        return "TEAM_SCORES_BOTH_HALVES", explicit_team_owner()
    if "wygraja jedna z polow" in semantic_title and explicit_team_owner():
        return "TEAM_WINS_ONE_HALF", explicit_team_owner()
    if "wygraja obie polowy" in semantic_title and explicit_team_owner():
        return "TEAM_WINS_BOTH_HALVES", explicit_team_owner()
    if (("oba zesp" in semantic_title or "obie druzyny" in semantic_title) and
            ("glo" in semantic_title or "gowa" in semantic_title or
             "rzutu wolnego" in semantic_title or "free kick" in semantic_title)):
        return "UNSUPPORTED_SPECIALTY", ""

    # Explicit proposition titles which used to fall into GENERIC.  They are
    # deliberately title-driven: unknown titles still remain GENERIC.
    if "kto zdob" in semantic_title and (re.search(r"\b1\.?\s*bram", semantic_title) or "pierwsz" in semantic_title):
        return "FIRST_GOAL_TEAM", ""
    if "kto zdob" in semantic_title and "ostatni" in semantic_title and "bram" in semantic_title:
        return "LAST_GOAL_TEAM", ""
    if "brak gola" in semantic_title or "bez gola" in semantic_title:
        return "NO_GOAL", ""
    if "gol z rzutu karnego" in semantic_title or "penalty goal" in semantic_title:
        return "PENALTY_GOAL", ""
    if "obaj gracze strzela" in semantic_title or "wszyscy strzela" in semantic_title or ("zdobedzie bramke" in semantic_title and "gracze" in semantic_title):
        return "PLAYER_COMBINATION", ""
    if "przewaga dwoma bramkami lub wygrana" in semantic_title:
        return "EARLY_WIN_OR_TWO_GOAL_LEAD", ""
    if ("oba zesp" in semantic_title and "strzela" in semantic_title and "liczba bramek" in semantic_title) or ("oba zesp" in semantic_title and "strzela" in semantic_title and " lub " in semantic_title) or ("btts" in semantic_title and (" lub " in semantic_title or " i " in semantic_title)):
        return "COMPOUND_LOGIC", ""

    # Half-time/full-time is an ordered compound pair.  It must precede normal
    # result recognition so neither half nor full-time component is discarded.
    if "/" in tl and "wynik" in tl and "po" in tl and "ca" in tl:
        return "HALF_FULL_RESULT", ""

    # ── CORRECT SCORE ────────────────────────────────────────────────────────
    if semantic_title == "dokladny wynik w grupie":
        return "CORRECT_SCORE_GROUP", ""
    if any(x in tl for x in ["dokładny wynik", "dokladny wynik", "correct score"]):
        return "CORRECT_SCORE", ""

    # ── MYCOMBI ──────────────────────────────────────────────────────────────
    if "mycombi" in tl:
        return "MYCOMBI", ""

    # Draw-no-bet is a two-selection result market, never a three-way handicap.
    if any(x in tl for x in ("remis - zwrot", "draw no bet", "dnb")):
        return "DNB", ""

    # The title is explicit compound semantics.  Keep it ahead of generic result
    # market matching so each goal threshold remains an independent canonical row.
    if any(x in tl for x in ("wynik i gole", "wynik i liczba bramek", "result and goals")):
        return "RESULT_AND_GOALS", ""

    # ── DOUBLE CHANCE ────────────────────────────────────────────────────────
    if any(x in tl for x in ["podwójna szansa", "podwojna szansa", "double chance"]):
        return "DOUBLE_CHANCE", ""

    # ── BTTS ─────────────────────────────────────────────────────────────────
    if any(x in tl for x in ["oba zespoły strzelą", "oba zespoly strzelą", "oba strzelą",
                               "obie drużyny", "btts", "oba zespoły", "oba zespoly"]):
        return "BTTS", ""

    # ── 1X2 ──────────────────────────────────────────────────────────────────
    if any(x in tl for x in ["wynik meczu", "wynik 1x2", "1x2", "wynik:"]):
        return "1X2", ""
    if tl in ("wynik", "wynik meczu") or (("wynik" in tl or "1x2" in tl) and ("połow" in tl or "polow" in tl or "half" in tl)):
        return "1X2", ""

    # ── EUROPEAN HANDICAP ────────────────────────────────────────────────────
    if "handicap" in tl:
        return "HANDICAP_EUROPEAN", ""

    # ── TEAM TOTALS ───────────────────────────────────────────────────────────
    # Must check before generic GOALS_OU
    if any(x in tl for x in ["liczba goli", "gole"]):
        # Does the market title contain a team name?
        if home_team and home_team.lower() in tl:
            return "TEAM_TOTALS_HOME", home_team
        if away_team and away_team.lower() in tl:
            return "TEAM_TOTALS_AWAY", away_team

        # Fallback keywords
        home_kw = ["gospodarz", "drużyna 1", "druzyna 1", "team 1"]
        away_kw  = ["gość", "gosc", "gości", "drużyna 2", "druzyna 2", "team 2"]
        if any(k in tl for k in home_kw):
            return "TEAM_TOTALS_HOME", home_team or "HOME"
        if any(k in tl for k in away_kw):
            return "TEAM_TOTALS_AWAY", away_team or "AWAY"

    # ── GOALS OVER/UNDER ─────────────────────────────────────────────────────
    if _player_score_and_total_line(market_title):
        return "PLAYER_PROP", ""
    if any(x in tl for x in ["suma goli", "suma bramek", "powyżej/poniżej", "powyżej", "poniżej",
                               "over/under", "over", "under", "o/u"]):
        return "GOALS_OU", ""

    # ── PLAYER PROP (line-based) ─────────────────────────────────────────────
    # These two grouped assist tables expose the player in the bounded row and
    # the threshold in its bounded column.  Keep the title allow-list exact:
    # assist/result compounds, combinations and Xtra offers are different
    # contracts and must remain fail-closed until audited independently.
    if _is_player_assist_threshold_market_title(market_title):
        return "PLAYER_PROP", ""

    player_line_markets = [
        "liczba strzałów",
        "strzały celne",
        "liczba celnych strzałów",
        "liczba fauli",
        "faule",
        "liczba dryblowań",
        "liczba podań",
        "liczba odbiorów",
        "żółte kartki",
        "kartki",
    ]
    # A shots/cards/fouls keyword also occurs in aggregate match and team
    # statistics.  Classifying those offers as player props corrupted both
    # semantic accounting and optional-statistics readiness.  Require an
    # explicit player-scope marker in the market title; a vague section name is
    # not sufficient provenance for a player proposition.
    player_scope_markers = ("zawodnik", "player", "gracz")
    if (
        any(x in tl for x in player_line_markets) or
        _is_inline_player_ou_single_market_title(market_title)
    ) and any(marker in semantic_title for marker in player_scope_markers):
        return "PLAYER_PROP", ""

    # Betclic team scoring-method cards use a team-suffixed title and binary
    # Tak/Nie outcomes.  The broad scorer keywords below must not turn these
    # team propositions into player-scoped GOALSCORER records.
    team_scoring_owner = explicit_team_owner()
    if (
        team_scoring_owner
        and semantic_selection in {"tak", "nie", "yes", "no"}
        and semantic_title.startswith(("strzela gola ", "team to score "))
    ):
        return "BINARY_EVENT", team_scoring_owner

    # ── GOALSCORER ────────────────────────────────────────────────────────────
    if _is_scorer_assister_regular_time_title(market_title):
        return "PLAYER_COMBINATION", ""
    if _player_goal_combination_contract(market_title, selection):
        return "PLAYER_COMBINATION", ""
    if _is_player_outscores_opponent_title(market_title):
        return "PLAYER_PROP", ""

    goal_assist_title = _semantic_text(market_title)
    if goal_assist_title == _PLAYER_GOAL_ASSIST_XTRA_TITLE:
        return "PLAYER_PROP_XTRA", ""
    if goal_assist_title in _PLAYER_GOAL_ASSIST_SINGLE_TITLES:
        return "PLAYER_PROP", ""
    if goal_assist_title in _PLAYER_GOAL_ASSIST_COMBINATION_TITLES:
        return "PLAYER_COMBINATION", ""
    if goal_assist_title in _PLAYER_ASSIST_COMBINATION_TITLES:
        return "PLAYER_COMBINATION", ""
    if goal_assist_title == _PLAYER_ASSIST_XTRA_TITLE:
        return "PLAYER_PROP_XTRA", ""
    if goal_assist_title == _PLAYER_PENALTY_CONVERSION_TITLE:
        return "GOALSCORER", ""

    scorer_kw = ["strzelec", "strzelić", "gola", "strzelca", "strzeli", "goalscorer",
                 "anytime", "first goal"]
    if semantic_title in {"strzelcy", "scorers"} or any(x in tl for x in scorer_kw):
        return "GOALSCORER", ""

    # ── HALF MARKETS ─────────────────────────────────────────────────────────
    if any(x in tl for x in ["1. połowa", "1. polowa", "2. połowa", "2. polowa",
                               "pierwsza połowa", "druga połowa", "1st half", "2nd half"]):
        return "HALF_MARKETS", ""

    return "GENERIC", ""


def classify_period(market_title: str, section_title: str, category: str = "", ancestor_title: str = "") -> str:
    combined = f"{market_title} {section_title} {category} {ancestor_title}".lower()

    p1_words = [
        "1. połowa", "1. polowa", "1 połowa", "1 polowa", "1.połowa", "1.polowa",
        "pierwsza połowa", "pierwsza polowa", "1. połie", "1. połowy", "1. polowy",
        "1. połowie", "1. polowie", "1 połowie", "1 polowie", "w 1. połowie", "w 1. polowie",
        "1. poł", "1. pol", "1 poł", "1 pol", "1st half", "half 1", "1st h", "halftime"
    ]
    if any(x in combined for x in p1_words) or re.search(r"\b1h\b", combined):
        return "1ST_HALF"

    p2_words = [
        "2. połowa", "2. polowa", "2 połowa", "2 polowa", "2.połowa", "2.polowa",
        "druga połowa", "druga polowa", "2. połie", "2. połowy", "2. polowy",
        "2. połowie", "2. polowie", "2 połowie", "2 polowie", "w 2. połowie", "w 2. polowie",
        "2. poł", "2. pol", "2 poł", "2 pol", "2nd half", "half 2", "2nd h"
    ]
    if any(x in combined for x in p2_words) or re.search(r"\b2h\b", combined):
        return "2ND_HALF"

    return "FULL_TIME"


def classify_scorer_scope(market_title: str, section_title: str, category: str = "", ancestor_title: str = "") -> str:
    combined = f"{market_title} {section_title} {category} {ancestor_title}".lower()

    if any(x in combined for x in ["pierwszy strzelec", "first scorer", "1. gola", "1.gola", "pierwszego gola", "pierwszy gol", "1st goal", "first goal"]):
        return "FIRST_GOAL"
    if any(x in combined for x in ["ostatni strzelec", "last scorer", "ostatniego gola", "ostatni gol", "last goal"]):
        return "LAST_GOAL"
    if any(x in combined for x in ["2 lub więcej", "2+ goli", "multigoal", "2 goals or more"]):
        return "MULTI_GOALS"

    return "ANYTIME"


def scorer_scope(market_title: str) -> str:
    """Explicit scorer offer scope used in canonical de-duplication."""
    title = market_title.lower()
    if "supersub" in title:
        return "SUPERSUB_ANYTIME"
    if "pierwszy" in title or "first" in title or "1. gola" in title:
        return "FIRST_GOAL"
    if "ostatni" in title or "last" in title:
        return "LAST_GOAL"
    return "ANYTIME"


def _period_text(value: str) -> str:
    value = (value or "").replace("ł", "l").replace("Ł", "L")
    return " ".join(unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower().split())


_GENERIC_RESULT_TITLES = frozenset({"wynik", "1x2", "wynik 1x2"})
_TIME_WINDOW_EVIDENCE = re.compile(
    r"\b\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2}\b"
    r"|\b\d{1,3}\s*(?:[-–]|do)\s*\d{1,3}\.?\s*(?:min\b|minut|')"
    r"|\b(?:pierwsz\w*|ostatni\w*)\s+\d{1,2}\s*minut"
    r"|\b\d{1,2}\.?\s*minut"
    r"|\bprzedzia\w*\s+czasow"
)


# Betclic "Fast" cards ("Wynik", "Gole", "Zawodnik strzeli" ...) settle on a
# user-selectable minute window rendered in the card header as
# "00:00 - 14:59 Edytuj".  The same card is also shown in the Top and
# Strzelcy tabs, where only the card text carries the window (live
# 2026-10-01, Borussia Dortmund - Werder: "Zawodnik strzeli" Guirassy 13
# was accepted as a full-match anytime scorer).
_SELECTABLE_WINDOW = re.compile(
    r"\b\d{1,2}[:.]\d{2}\s*[-–]\s*(?:\d{1,2}[:.]\d{2}|przerwa|koniec\b[^0-9]{0,30}?)\s*edytuj\b",
    re.IGNORECASE)


def has_selectable_time_window(box_context: str) -> bool:
    """Whether a market card declares an editable minute window (Fast market)."""
    return bool(_SELECTABLE_WINDOW.search(str(box_context or "")))


def is_fast_window_tab(tab: str) -> bool:
    """The "⚡ Fast" tab only lists minute-window markets."""
    return "fast" in _period_text(tab).split()


def classify_period_detail(market_title: str, section_title: str, period_hint: str = "",
                           ancestor_title: str = "", main_tab: str = "",
                           family: str = "") -> tuple[str, str, str]:
    """Resolve period from explicit evidence, never from an unexplained FT default."""
    sources = (("CELL_PERIOD_HINT", period_hint), ("SECTION_TITLE", section_title),
               ("PARENT_CONTEXT", ancestor_title), ("MARKET_TITLE", market_title),
               ("TAB_CONTEXT", main_tab))
    title = _period_text(market_title)
    # Betclic PL terms captured 2026-09-05; see docs/SEMANTICS_20260905.md.
    # These exact statistic contracts include the match and any extra time,
    # never an extra-time-only football result or a 120-minute wall clock.
    extra_statistic = bool(re.fullmatch(
        r"(?:1x2 strzaly \(120 min\)|strzaly celne - 1x2 \(opta\)|"
        r"liczba (?:celnych )?strzalow (?:zawodnika|w meczu) \(opta\)(?: - .+)?|"
        r"liczba kartek zawodnika)", title))
    half_evidence = {match.group(1) for _, value in sources
                     for match in re.finditer(r"\b([12])\.?\s*(?:polowa|half)\b", _period_text(value))}
    if len(half_evidence) > 1:
        return "UNKNOWN", "CONFLICTING_EXPLICIT_PERIODS", "LOW"
    for source, text in sources:
        value = _period_text(text)
        if re.search(r"(?:^|\s|\()120\s*min(?:\s|\)|$)", value):
            return ("MATCH_INCLUDING_EXTRA_TIME" if extra_statistic else "OTHER"), source, "HIGH"
        if any(int(minutes) != 90 for minutes in re.findall(r"\((\d+)\s*min\)", value)):
            return "OTHER", source, "HIGH"
        if re.search(r"(?:^|\s)(?:1\.?\s*(?:polowa|half)|pierwsza\s+polowa|1st\s+half)(?:\s|$)", value):
            return "1ST_HALF", source, "HIGH"
        if re.search(r"(?:^|\s)(?:2\.?\s*(?:polowa|half)|druga\s+polowa|2nd\s+half)(?:\s|$)", value):
            return "2ND_HALF", source, "HIGH"
        if any(token in value for token in ("awans", "rywalizacji", "kwalifik")):
            return "QUALIFICATION", source, "HIGH"
        if "w obu polowach" in value or "in both halves" in value:
            return "FULL_TIME", source, "HIGH"
        if any(token in value for token in ("bez dogrywki", "z wylaczeniem dogrywki",
                                             "excluding extra time", "regular time only")):
            return "FULL_TIME", source, "MEDIUM"
        if any(token in value for token in ("z dogrywka", "including extra time", "rzutow karn", "z karn")):
            return "OTHER", source, "HIGH"
        if any(token in value for token in ("90 min", "reg. czas", "czas reg.", "regular time", "full time", "full-time",
                                             "w meczu", "wynik meczu", "match result")):
            if source == "MARKET_TITLE" and extra_statistic and "w meczu" in value:
                return "MATCH_INCLUDING_EXTRA_TIME", "BETCLIC_PL_STATISTICS_RULE_20260905", "HIGH"
            return "FULL_TIME", source, "MEDIUM"
        # A minute window (e.g. "0-15 min", "00:00 - 14:59", "10 minut") is
        # explicit evidence of a sub-match interval.  It must never fall
        # through to the canonical full-time default below.
        if _TIME_WINDOW_EVIDENCE.search(value) or _TIME_WINDOW_EVIDENCE.search(str(text or "").casefold()):
            return "UNKNOWN", f"UNSUPPORTED_TIME_WINDOW:{source}", "LOW"
    if extra_statistic:
        return "MATCH_INCLUDING_EXTRA_TIME", "BETCLIC_PL_STATISTICS_RULE_20260905", "HIGH"
    regular_titles = {
        "zawodnik zaliczy asyste", "zawodnik zanotuje asyste",
        "zawodnik asystujacy + jego zmiennik",
        "zawodnik strzeli gola lub zaliczy asyste",
        "zawodnik strzeli gola lub zaliczy asyste + jego zmiennik",
        "zawodnik strzeli gola i zaliczy asyste",
        "zawodnik lub jego zmiennik strzeli gola i zaliczy asyste",
        "ktorykolwiek zawodnik strzeli gola lub zaliczy asyste",
        "obaj gracze strzela gola lub zalicza asyste",
        "ktorykolwiek zawodnik zaliczy asyste",
        "ktorykolwiek zawodnik zaliczy asyste - 3 zawodnikow",
        "rzuty rozne", "wiecej rzutow roznych", "wiecej kartek", "liczba kartek",
    }
    if title in regular_titles or re.fullmatch(r"kartki - .+", title):
        return "FULL_TIME", "BETCLIC_PL_REGULAR_TIME_RULE_20260905", "HIGH"
    canonical_ft = {"1X2", "DOUBLE_CHANCE", "BTTS", "GOALS_OU", "TEAM_TOTALS_HOME",
                    "TEAM_TOTALS_AWAY", "HANDICAP_EUROPEAN", "CORRECT_SCORE", "CORRECT_SCORE_GROUP", "GOALSCORER",
                    "DNB", "RESULT_AND_GOALS", "FIRST_GOAL_TEAM", "LAST_GOAL_TEAM", "NO_GOAL",
                    "PENALTY_GOAL", "PLAYER_COMBINATION", "EARLY_WIN_OR_TWO_GOAL_LEAD", "COMPOUND_LOGIC",
                    "GOAL_PARITY", "CLEAN_SHEET", "TEAM_WIN_TO_NIL", "EXACT_GOALS", "GOAL_RANGE", "HIGHER_SCORING_HALF",
                    "GOAL_MARGIN", "TEAM_SCORES_BOTH_HALVES", "TEAM_WINS_ONE_HALF", "TEAM_WINS_BOTH_HALVES",
                    "FIRST_GOAL_TIME", "QUALIFICATION_WINNER", "QUALIFICATION_METHOD", "BINARY_EVENT",
                    "EVENT_FIRST_LAST", "EVENT_RANGE", "EVENT_PARITY", "EVENT_EXACT", "EVENT_RESULT"}
    # A bare "Wynik" states neither period nor scope.  Betclic's full-match
    # result is titled "Wynik meczu (...)"; a bare "Wynik" was observed live
    # (2026-09-28, Szwecja - Polska: 5.00/1.30/7.75 beside the real FT 1X2
    # 1.93/3.78/3.73) on an interval market.  Without explicit period
    # evidence it stays unresolved instead of defaulting to FULL_TIME.
    if family == "1X2" and title in _GENERIC_RESULT_TITLES:
        return "UNKNOWN", "GENERIC_RESULT_TITLE_WITHOUT_PERIOD", "LOW"
    if family in canonical_ft:
        return "FULL_TIME", "CANONICAL_MARKET", "MEDIUM"
    # Versioned title ontology for explicit, full-match settlement offers.  This
    # is deliberately title/context based: unknown titles still fail closed.
    title = _period_text(market_title)
    full_match_ontology_v1 = (
        "suma goli", "zdobedzie bramke", "roznica goli", "wygraja obie polowy",
        "wygraja jedna z polow", "zwyciestwo do zera", "wynik i kto zdobedzie",
        "liczba goli - opcja", "bez utraty bramki", "dokladna liczba bramek",
        "strzela w obu polowach", "polowa z wieksza liczba goli", "polowa z wieksza iloscia goli", "gol z rzutu karnego",
        "liczba goli nieparzysta/parzysta", "gole nieparzyste/parzyste",
        "wynik i gole", "wynik meczu & oba zespoly strzelaja",
        "obaj gracze strzela", "wszyscy strzela",
    )
    if any(token in title for token in full_match_ontology_v1):
        return "FULL_TIME", "CANONICAL_MARKET", "MEDIUM"
    return "UNKNOWN", "UNRESOLVED", "LOW"


def classify_market_scope(market_title: str, period: str) -> str:
    title = _period_text(market_title)
    if period == "MATCH_INCLUDING_EXTRA_TIME": return "MATCH_INCLUDING_EXTRA_TIME"
    if period == "QUALIFICATION": return "QUALIFICATION"
    if period == "OTHER": return "OTHER"
    if period == "1ST_HALF": return "FIRST_HALF"
    if period == "2ND_HALF": return "SECOND_HALF"
    if any(token in title for token in ("90 min", "reg. czas", "czas reg.", "bez dogrywki",
                                        "z wylaczeniem dogrywki", "w meczu")):
        return "REGULAR_TIME"
    return "FULL_TIME" if period == "FULL_TIME" else "UNKNOWN"


def extract_line_value(market_title: str, selection: str, section_title: str) -> str:
    combined = f"{market_title} {section_title} {selection}"

    # Prefer signed decimal like -1.5, +2.5, 2.5
    m = re.search(r"([+\-]?\d+[\.,]\d+)", combined)
    if m:
        return m.group(1).replace(",", ".")

    # Signed integer like -2, +3
    m = re.search(r"([+\-]\d+)", combined)
    if m:
        return m.group(1)

    # Plain integer in market context (for OU line e.g. "2 Gole" in section)
    m = re.search(r"\b(\d+)\b", combined)
    if m:
        return m.group(1)

    return ""


def extract_player_line(text: str) -> str:
    """Extract numeric threshold from player prop text like 'Powyżej 2.5'."""
    m = re.search(r"(?:Powyżej|Poniżej|Over|Under)\s+([0-9]+[\.,]?[0-9]*)\b",
                  text, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", ".")
    return ""


def _classify_half_full_component(selection: str, home_team: str, away_team: str, native_team_names: dict | None = None) -> str:
    """Resolve a whole ordered component, never a substring inside another name."""
    token = _semantic_text(selection)
    literals = {"1": "HOME", "home": "HOME", "gospodarz": "HOME",
                "domowy": "HOME", "2": "AWAY", "away": "AWAY",
                "gosc": "AWAY", "gosci": "AWAY", "gosciny": "AWAY",
                "x": "DRAW", "remis": "DRAW", "draw": "DRAW"}
    if token in literals:
        return literals[token]

    def compact(value: str) -> str:
        text = re.sub(r"\butd\b\.?", "united", _semantic_text(value))
        return "".join(char for char in text if char.isalnum())

    source = compact(selection)
    teams = (("HOME", home_team), ("AWAY", away_team))
    exact = [side for side, team in teams if source and source == compact(team)]
    if exact:
        return exact[0] if len(exact) == 1 else ""
    evidence = native_team_names or {}
    if (evidence.get("schema") == "NATIVE_EVENT_TEAM_NAMES_V1"
            and evidence.get("home") == home_team and evidence.get("away") == away_team
            and evidence.get("event_id") and re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("snapshot_sha256", "")))):
        native = [side for side, key in (("HOME", "home_short"), ("AWAY", "away_short"))
                  if token and token == _semantic_text(str(evidence.get(key) or ""))]
        if native:
            return native[0] if len(native) == 1 else ""
    # Permit only omission of bounded club abbreviations at the name edges.
    # Native Betclic shortName pairs confirm forms such as CA Platense /
    # Platense and Pafos FC / Pafos. Preserve age, gender and regional tokens.
    # Arbitrary substring matching would accept foreign labels like Not Chlef.
    aliases = []
    for side, team in teams:
        parts = _semantic_text(team).split()
        if len(parts) > 1 and parts[0].rstrip(".") in {"fc", "ac", "cr", "cd", "sc", "cf", "as", "ca"}:
            parts = parts[1:]
        if len(parts) > 1 and parts[-1].rstrip(".") in {"fc", "ac", "sc", "cf"}:
            parts = parts[:-1]
        alias = compact(" ".join(parts))
        if len(alias) >= 4 and source == alias:
            aliases.append(side)
    return aliases[0] if len(aliases) == 1 else ""


def _classify_selection_side(selection: str, home_team: str, away_team: str) -> str:
    sl = selection.strip().lower()
    if sl in ("1", "domowy", "gospodarz", "home"):
        return "HOME"
    if sl in ("2", "gościny", "gość", "away", "gości"):
        return "AWAY"
    if sl in ("x", "remis", "draw"):
        return "DRAW"
    if home_team and home_team.lower() in sl:
        return "HOME"
    if away_team and away_team.lower() in sl:
        return "AWAY"
    return ""


def _classify_double_chance_selection(selection: str, home_team: str, away_team: str,
                                      native_team_names: dict | None = None) -> str:
    """Map literal or fully labelled double-chance pairs before team aliasing."""
    semantic = _semantic_text(selection)
    literal = re.sub(r"\s+", "", semantic).upper()
    if literal in {"1X", "12", "X2"}:
        return literal
    # Some compact capture cells retain the adjacent displayed price in the
    # selection string.  It is transport noise, not part of the double-chance
    # outcome; accept only a complete literal followed by one decimal price.
    priced_literal = re.fullmatch(r"(1x|12|x2)\s+\d+(?:[.,]\d+)?", semantic)
    if priced_literal:
        return priced_literal.group(1).upper()

    home = _semantic_text(home_team)
    away = _semantic_text(away_team)
    sides: set[str] = set()
    for component in re.split(r"\s+(?:lub|albo|or)\s+|\s*/\s*", semantic):
        if component in {"1", "home", "gospodarz", "domowy"} or (home and component == home):
            sides.add("HOME")
        elif component in {"x", "remis", "draw"}:
            sides.add("DRAW")
        elif component in {"2", "away", "gosc", "goscie"} or (away and component == away):
            sides.add("AWAY")
        else:
            # Betclic labels double chance with the page's native short names
            # (Juventude RS -> "Juventude").  Resolve a whole component with the
            # same event-scoped evidence as half/full components, never fuzzily.
            side = _classify_half_full_component(component, home_team, away_team, native_team_names)
            if side:
                sides.add(side)

    return {
        frozenset({"HOME", "DRAW"}): "1X",
        frozenset({"HOME", "AWAY"}): "12",
        frozenset({"DRAW", "AWAY"}): "X2",
    }.get(frozenset(sides), "")


def _determine_handicap_line(market_title: str, selection: str, section_title: str,
                              home_team: str, away_team: str) -> tuple[str, str]:
    """
    For European Handicap, determine signed line and side (HOME/DRAW/AWAY).
    Returns (line_str, side).
    """
    # A handicap line belongs to the selectable row, not to a neighbouring market
    # title/section.  Reading the combined text caused -3/-1 rows to inherit -2.
    parenthesized = re.search(r"\([^)]*?([+\-]\d+[\.,]?\d*)\)\s*$", selection)
    # Club names can themselves contain a hyphenated number (e.g. Kaspiy-2);
    # the terminal parenthesized value is the only row-local handicap evidence.
    numbers = [parenthesized.group(1)] if parenthesized else re.findall(r"([+\-]\d+[\.,]?\d*)", selection)
    sel_low = selection.lower()

    # Determine side first
    side = ""
    if "remis" in sel_low or sel_low == "x":
        side = "DRAW"
    elif home_team and home_team.lower() in sel_low:
        side = "HOME"
    elif away_team and away_team.lower() in sel_low:
        side = "AWAY"
    elif "1" == sel_low.strip():
        side = "HOME"
    elif "2" == sel_low.strip():
        side = "AWAY"

    # Pick the correct signed line based on side
    if numbers:
        neg_nums = [n for n in numbers if n.startswith("-")]
        pos_nums = [n for n in numbers if n.startswith("+")]

        if side == "HOME":
            return (neg_nums[0].replace(",", ".") if neg_nums else numbers[0].replace(",", ".")), side
        elif side == "AWAY":
            return (pos_nums[0].replace(",", ".") if pos_nums else numbers[-1].replace(",", ".")), side
        elif side == "DRAW":
            return (neg_nums[0].replace(",", ".") if neg_nums else numbers[0].replace(",", ".")), side
        else:
            return numbers[0].replace(",", "."), side

    return "", side


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RECORD BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def parse_market_record(
    *,
    category: str,
    market_title: str,
    raw_selection: str,
    odds_str: str,
    raw_text: str,
    section_title: str,
    home_team: str,
    away_team: str,
    container_id: str,
    period_hint: str = "",
    ancestor_title: str = "",
    main_tab: str = "",
    settlement_scope_hint: str = "",
    participant_hint: str | None = None,
    line_hint: str = "",
    handicap_kind_hint: str = "",
    market_instance_id: str = "",
    run_id: str = "", event_id: str = "", source_hash: str = "",
    raw_record_id: str = "", source_raw_record_ids: list[str] | None = None,
    native_team_names: dict | None = None,
) -> tuple[dict | None, dict | None]:
    """
    Returns (odd_record, unresolved_record).
    Exactly one of the two will be non-None.
    """
    if not market_title or not odds_str:
        return None, None

    try:
        odds_f = float(odds_str.replace(",", "."))
    except ValueError:
        return None, None

    if odds_f < 1.01 or odds_f > 1000.0:
        return None, None

    pre_family, pre_owner_raw = classify_family(market_title, raw_selection, section_title,
                                                 home_team, away_team)
    if pre_family in {"DOUBLE_CHANCE", "HALF_FULL_RESULT", "COMPOUND_LOGIC"}:
        canonical_raw_selection, alias_status = raw_selection, ""
        family, owner_raw = pre_family, pre_owner_raw
    else:
        canonical_raw_selection, alias_status = canonical_event_team_name(raw_selection, home_team, away_team)
        family, owner_raw = classify_family(market_title, canonical_raw_selection, section_title,
                                             home_team, away_team)
    hint_semantic = _semantic_text(period_hint)
    # Compact Top cards may truncate the market title, but retain an explicit
    # first/last-goal heading as scoped evidence.  Do not infer beyond that.
    if family == "GENERIC" and "zdob" in _semantic_text(market_title):
        if "pierwsz" in hint_semantic:
            family = "FIRST_GOAL_TEAM"
        elif "ostatni" in hint_semantic:
            family = "LAST_GOAL_TEAM"
    assist_result_condition = _assist_result_condition(market_title, period_hint)
    scorer_assister_pair = _is_scorer_assister_regular_time_title(market_title)
    goal_assist_single_kind = _goal_assist_single_kind(market_title)
    goal_assist_combination_mode = _goal_assist_combination_mode(market_title)
    pure_assist_combination_mode = _pure_assist_combination_mode(market_title)
    pure_assist_xtra = _is_pure_assist_xtra_title(market_title)
    player_penalty_conversion = _is_player_penalty_conversion_title(market_title)
    player_score_total_line = _player_score_and_total_line(market_title)
    player_goal_combination = _player_goal_combination_contract(
        market_title, canonical_raw_selection,
    )
    player_outscores_opponent = _is_player_outscores_opponent_title(market_title)
    match_compound = _match_compound_contract(
        market_title, canonical_raw_selection, home_team, away_team,
    )
    if family == "GENERIC" and assist_result_condition:
        family = "PLAYER_PROP"
    # A half heading with an explicit over/under selection is still a normal
    # goals-total market; only its period differs.  Leaving it as the broad
    # HALF_MARKETS bucket lost its line and settlement.
    selection_semantic = _semantic_text(canonical_raw_selection)
    if family == "HALF_MARKETS" and ("powyzej" in selection_semantic or "ponizej" in selection_semantic or
                                      " over " in f" {selection_semantic} " or " under " in f" {selection_semantic} "):
        family = "GOALS_OU"
    period, period_source, period_confidence = classify_period_detail(
        market_title, section_title, period_hint, ancestor_title, main_tab or category, family
    )
    contract_title = _contract_text(market_title)
    if contract_title == "podwojna szansa (1.polowa lub mecz)":
        period, period_source, period_confidence = "FULL_TIME", "MARKET_TITLE", "HIGH"
    if (_semantic_text(str(market_title).replace("ł", "l").replace("Ł", "L"))
            in _EXACT_SPECIALTIES_REQUIRING_TIME_EVIDENCE
            and period_source == "CANONICAL_MARKET"):
        # These exact contracts prove outcome and payout shape, not a match
        # duration.  A family-level FT default would create a false accept.
        period, period_source, period_confidence = "UNKNOWN", "UNRESOLVED", "LOW"
    if (_audited_event_contract_requires_time_evidence(market_title, home_team, away_team)
            and period_source == "CANONICAL_MARKET"):
        period, period_source, period_confidence = "UNKNOWN", "UNRESOLVED", "LOW"
    if ((goal_assist_combination_mode or pure_assist_combination_mode)
            and period_source == "CANONICAL_MARKET"):
        # The participant connective is explicit, but these exact titles carry
        # no match/half scope.  PLAYER_COMBINATION's generic FT default is not
        # valid evidence for a goal-or-assist proposition.
        period, period_source, period_confidence = "UNKNOWN", "UNRESOLVED", "LOW"
    market_scope = classify_market_scope(market_title, period)
    explicit_scope = settlement_scope_hint.strip().upper()
    scope_periods = {"FULL_TIME": "FULL_TIME", "REGULAR_TIME": "FULL_TIME",
                     "FIRST_HALF": "1ST_HALF", "SECOND_HALF": "2ND_HALF",
                     "QUALIFICATION": "QUALIFICATION", "OTHER": "OTHER"}
    if explicit_scope in scope_periods:
        period = scope_periods[explicit_scope]
        market_scope = explicit_scope
        period_source, period_confidence = "SETTLEMENT_SCOPE_HINT", "HIGH"
    column_role = _column_role_from_instance(market_instance_id)
    scorer_result_condition = (
        _scorer_result_condition(market_title, column_role)
        or _scorer_result_condition(market_title, period_hint)
    )
    scorer_substitute_selection, scorer_substitute_scope = _scorer_substitute_threshold(
        market_title, column_role,
    )
    if not scorer_substitute_selection:
        scorer_substitute_selection, scorer_substitute_scope = _scorer_substitute_threshold(
            market_title, period_hint,
        )
    if player_goal_combination:
        scorer_scope_value = str(player_goal_combination["scope"])
        column_semantics_status = "PROVEN" if scorer_scope_value else "NOT_APPLICABLE"
    elif player_outscores_opponent:
        scorer_scope_value, column_semantics_status = "", "NOT_APPLICABLE"
    elif scorer_result_condition:
        scorer_scope_value = ("ANYTIME_SUPERSUB" if scorer_result_condition.startswith(
            "SCORER_OR_SUBSTITUTE_") else "ANYTIME")
        column_semantics_status = "PROVEN"
    elif scorer_substitute_selection:
        scorer_scope_value, column_semantics_status = scorer_substitute_scope, "PROVEN"
    elif (assist_result_condition or scorer_assister_pair or goal_assist_single_kind
            or goal_assist_combination_mode or pure_assist_combination_mode
            or pure_assist_xtra):
        # This column describes a compound assist predicate, not a goal-count
        # or anytime-scorer scope.
        scorer_scope_value, column_semantics_status = "", "NOT_APPLICABLE"
    elif player_penalty_conversion:
        scorer_scope_value, column_semantics_status = "ANYTIME", "PROVEN"
    elif family in {"GOALSCORER", "PLAYER_PROP", "PLAYER_COMBINATION"}:
        scorer_scope_value, column_semantics_status = scorer_scope_from_evidence(
            f"{market_title} {section_title} {ancestor_title}", column_role
        )
        if not scorer_scope_value:
            scorer_scope_value = classify_scorer_scope(market_title, section_title, category, ancestor_title)
    else:
        scorer_scope_value, column_semantics_status = "", "NOT_APPLICABLE"

    selection = deduplicate_owner_name(canonical_raw_selection.strip())
    owner = deduplicate_owner_name(owner_raw.strip()) if owner_raw else ""
    # Betclic's two-column team markets frequently carry the owner in the
    # column/period hint rather than in the market title.  It is preserved
    # evidence, not an inferred default; absent or conflicting hints remain
    # ownerless and therefore fail closed where ownership is required.
    hint_owner = _semantic_text(period_hint)
    if not owner and family in {"CLEAN_SHEET", "TEAM_WIN_TO_NIL", "TEAM_SCORES_BOTH_HALVES", "TEAM_WINS_ONE_HALF", "TEAM_WINS_BOTH_HALVES"}:
        if hint_owner in {"gospodarze", "home", "team 1"}:
            owner = home_team
        elif hint_owner in {"goscie", "away", "team 2"}:
            owner = away_team
    participant = ""
    participants: list[str] = []
    team_owner_status = "NOT_APPLICABLE"

    line = ""
    settlement = "PUSH_ON_DRAW" if family == "DNB" else "UNKNOWN"

    # ── Family-specific overrides ──────────────────────────────────────────

    if family == "HANDICAP_EUROPEAN":
        line, side = _determine_handicap_line(market_title, raw_selection,
                                               section_title, home_team, away_team)
        if side:
            selection = side

    elif family in ("GOALS_OU", "TEAM_TOTALS_HOME", "TEAM_TOTALS_AWAY", "EVENT_TOTAL"):
        line = extract_line_value(market_title, raw_selection, section_title)
        # side: Powyżej → OVER, Poniżej → UNDER
        if "powyżej" in raw_selection.lower() or "over" in raw_selection.lower():
            selection = "OVER"
        elif "poniżej" in raw_selection.lower() or "under" in raw_selection.lower():
            selection = "UNDER"

    elif family in {"PLAYER_PROP", "PLAYER_PROP_XTRA"}:
        # Slider rows provide an explicit participant bounded by their own
        # sports-slider-value.  An explicit empty hint remains fail-closed;
        # legacy callers without this evidence retain their prior behaviour.
        inline_player_ou = _is_inline_player_ou_single_market_title(market_title)
        assist_threshold = _is_player_assist_threshold_market_title(market_title)
        if participant_hint is not None:
            player_name = participant_hint.strip()
        elif inline_player_ou:
            # This single-market template co-locates player, outcome and line
            # inside one row-local marketBox_label.  The section title is the
            # team owner and must never replace the row's player participant.
            inline_match = re.fullmatch(
                r"\s*(.+?)\s+(?:Powyżej|Poniżej|Over|Under)\s+[0-9]+(?:[.,][0-9]+)?\s*",
                raw_selection,
                re.IGNORECASE,
            )
            player_name = inline_match.group(1).strip() if inline_match else ""
        elif assist_threshold:
            # Grouped assist tables use the row label itself as the player;
            # section ancestry is generic/stale and is never participant proof.
            player_name = raw_selection.strip()
        elif assist_result_condition:
            # The exact condition is bounded by the same grouped row as this
            # selection; generic/stale section ancestry is not entity evidence.
            player_name = raw_selection.strip()
        elif goal_assist_single_kind:
            player_name = raw_selection.strip()
        elif pure_assist_xtra:
            player_name = raw_selection.strip()
        elif player_score_total_line:
            player_name = raw_selection.strip()
        elif player_outscores_opponent:
            player_name = raw_selection.strip()
        else:
            player_name = section_title.strip() if section_title else ""
        if (participant_hint is None and not player_name and not inline_player_ou
                and not assist_threshold and not assist_result_condition
                and not goal_assist_single_kind and not pure_assist_xtra
                and not player_score_total_line and not player_outscores_opponent):
            # Try to find name before "Powyżej"/"Poniżej"
            m = re.match(r"^(.*?)\s*(?:Powyżej|Poniżej|Over|Under)", raw_selection, re.IGNORECASE)
            if m:
                player_name = m.group(1).strip()
        participant = deduplicate_owner_name(player_name)
        participants = [participant] if participant else []
        team_owner, owner_status = canonical_event_team_name(section_title, home_team, away_team)
        owner = team_owner if owner_status else ""
        team_owner_status = "TEAM_OWNER_CONFIRMED" if owner else "TEAM_OWNER_UNKNOWN"
        line = extract_player_line(raw_text)
        if not line:
            line = extract_player_line(f"{raw_selection} {section_title}")
        if not line and assist_threshold:
            line = _assist_threshold_line(market_title, period_hint)
        if not line and goal_assist_single_kind:
            line = _goal_assist_threshold_line(market_title, period_hint)
        if not line and player_score_total_line:
            line = player_score_total_line
        goal_assist_result = _goal_assist_result_condition(market_title, period_hint)
        if "powyżej" in raw_selection.lower() or "over" in raw_selection.lower():
            selection = "OVER"
        elif "poniżej" in raw_selection.lower() or "under" in raw_selection.lower():
            selection = "UNDER"
        elif assist_threshold and line:
            selection = "OVER"
        elif assist_result_condition:
            selection = assist_result_condition
        elif goal_assist_result:
            selection = goal_assist_result
        elif goal_assist_single_kind == "AND":
            selection = "GOAL_AND_ASSIST"
        elif goal_assist_single_kind == "XTRA_OR":
            selection = "GOAL_OR_ASSIST_XTRA"
        elif goal_assist_single_kind == "OR":
            selection = "OVER" if line else "GOAL_OR_ASSIST"
        elif pure_assist_xtra:
            selection = "ASSIST_XTRA"
        elif player_score_total_line:
            selection = "SCORE_AND_TOTAL_OVER"
        elif player_outscores_opponent:
            selection = "OUTSCORES_OPPONENT"

    elif family == "GOALSCORER":
        # A player is a participant, never a team OWNER.  Section ancestry is
        # used only when it exactly identifies one event team.
        candidate = deduplicate_owner_name(canonical_raw_selection.strip())
        if candidate and _period_text(candidate) not in {"tak", "nie", "yes", "no"}:
            participants = [deduplicate_owner_name(piece.strip()) for piece in
                            re.split(r"\s*(?:/|,|\bi\b|\boraz\b|\band\b)\s*", candidate, flags=re.IGNORECASE)
                            if piece.strip()]
            participant = participants[0] if len(participants) == 1 else ""
        team_owner, owner_status = canonical_event_team_name(section_title, home_team, away_team)
        owner = team_owner if owner_status else ""
        team_owner_status = "TEAM_OWNER_CONFIRMED" if owner else "TEAM_OWNER_UNKNOWN"
        if scorer_result_condition:
            selection = scorer_result_condition
        elif scorer_substitute_selection:
            selection = scorer_substitute_selection

    elif family in ("1X2", "DNB", "EVENT_RESULT"):
        side = _classify_selection_side(canonical_raw_selection, home_team, away_team)
        if side:
            selection = side
            owner = home_team if side == "HOME" else away_team if side == "AWAY" else ""

    elif family == "HALF_FULL_RESULT":
        components = re.split(r"\s*/\s*", canonical_raw_selection.strip())
        if len(components) == 2:
            sides = [_classify_half_full_component(component, home_team, away_team, native_team_names)
                     for component in components]
            if all(side in {"HOME", "DRAW", "AWAY"} for side in sides):
                selection = "_".join(sides)

    elif family == "EVENT_FIRST_LAST":
        side = _classify_selection_side(canonical_raw_selection, home_team, away_team)
        if side in {"HOME", "AWAY"}:
            selection = side
            owner = home_team if side == "HOME" else away_team
        elif _contract_text(canonical_raw_selection) in {"nikt", "bez kartek"}:
            selection, owner = "NO_EVENT", ""

    elif family == "RESULT_AND_GOALS":
        line = extract_line_value("", raw_selection, "")
        # This is a compound settlement: the result and the goal direction are
        # both material.  Retaining only HOME/AWAY/DRAW made over/under pairs
        # look like identical canonical offers and allowed a later dedupe to
        # discard one of them.
        compound_text = _period_text(raw_selection)
        home_text = _period_text(home_team)
        away_text = _period_text(away_team)
        result_part = ("DRAW" if "remis" in compound_text else
                       "HOME" if home_text and home_text in compound_text else
                       "AWAY" if away_text and away_text in compound_text else "")
        goals_part = ("OVER" if "powyzej" in compound_text or " over " in f" {compound_text} " else
                      "UNDER" if "ponizej" in compound_text or " under " in f" {compound_text} " else "")
        if result_part and goals_part:
            selection = f"{result_part}_AND_{goals_part}"
            owner = home_team if result_part == "HOME" else away_team if result_part == "AWAY" else ""
            settlement = f"{result_part}_AND_{goals_part}_{line}" if line else f"{result_part}_AND_{goals_part}"

    elif family in {"FIRST_GOAL_TEAM", "LAST_GOAL_TEAM", "EARLY_WIN_OR_TWO_GOAL_LEAD"}:
        side = _classify_selection_side(canonical_raw_selection, home_team, away_team)
        if side:
            selection = side
            owner = home_team if side == "HOME" else away_team if side == "AWAY" else ""

    elif family in {"PENALTY_GOAL", "NO_GOAL"}:
        token = _semantic_text(canonical_raw_selection)
        if token in {"tak", "yes"}:
            selection = "YES"
        elif token in {"nie", "no"}:
            selection = "NO"

    elif family == "TEAM_WIN_TO_NIL":
        token = _contract_text(canonical_raw_selection)
        selection = {"tak": "YES", "yes": "YES", "nie": "NO", "no": "NO"}.get(
            token, canonical_raw_selection,
        )

    elif family == "PLAYER_COMBINATION":
        # Preserve every named participant in source order.  The UI normally
        # separates names with a conjunction; no inferred team ownership.
        if player_goal_combination:
            pieces = canonical_raw_selection.split(str(player_goal_combination["delimiter"]))
        elif pure_assist_combination_mode:
            pieces = re.split(r"\s*/\s*", canonical_raw_selection)
        elif goal_assist_combination_mode == "ANY_GOAL_OR_ASSIST":
            pieces = re.split(r"\s*/\s*", canonical_raw_selection)
        elif goal_assist_combination_mode == "ALL_GOAL_OR_ASSIST":
            pieces = re.split(r"\s*&\s*", canonical_raw_selection)
        else:
            pieces = re.split(r"\s*(?:/|,|\bi\b|\boraz\b|\band\b)\s*", canonical_raw_selection, flags=re.IGNORECASE)
        participants = [deduplicate_owner_name(piece.strip()) for piece in pieces if piece.strip()]
        participant = participants[0] if len(participants) == 1 else ""
        if player_goal_combination:
            selection = str(player_goal_combination["mode"])
            line = str(player_goal_combination["line"])
        elif goal_assist_combination_mode:
            selection = goal_assist_combination_mode
        elif pure_assist_combination_mode:
            selection = pure_assist_combination_mode
        if scorer_assister_pair:
            selection = "SCORER_AND_ASSISTER"
            team_owner, owner_status = canonical_event_team_name(section_title, home_team, away_team)
            owner = team_owner if owner_status else ""
            team_owner_status = "TEAM_OWNER_CONFIRMED" if owner else "TEAM_OWNER_UNKNOWN"

    elif family == "COMPOUND_LOGIC":
        if match_compound:
            selection = match_compound["selection"]
            line = match_compound["line"]
        else:
            # "ł" has no ASCII decomposition and would silently vanish
            # ("Włochy" -> "WOCHY", "zespół" -> "ZESPO"); transliterate it first.
            condition = _semantic_text(str(canonical_raw_selection).replace("ł", "l").replace("Ł", "L"))
            # Preserve the source condition as semantic selection; explicit
            # normalisation below supplies equivalence only for proven forms.
            selection = condition.upper().replace(" ", "_")

    elif family == "DOUBLE_CHANCE":
        double_chance = _classify_double_chance_selection(raw_selection, home_team, away_team, native_team_names)
        if double_chance:
            selection = double_chance

    elif family == "BTTS":
        if raw_selection.lower() in ("tak", "yes", "true"):
            selection = "TAK"
        elif raw_selection.lower() in ("nie", "no", "false"):
            selection = "NIE"

    if line_hint.strip() and not line:
        line = line_hint.strip().replace(",", ".")

    # ── Build final record ──────────────────────────────────────────────────

    explicit_two_way_handicap = family == "HANDICAP_EUROPEAN" and (
        "2-dro" in _period_text(market_title)
        or "rzuty rozne handicap" in _period_text(market_title)
        or "corners handicap" in _period_text(market_title)
    )
    handicap_kind = ("TWO_WAY" if explicit_two_way_handicap else
                     (handicap_kind_hint if family == "HANDICAP_EUROPEAN" and handicap_kind_hint in ("TWO_WAY", "THREE_WAY", "ASIAN")
                      else ("THREE_WAY" if family == "HANDICAP_EUROPEAN" else "")))
    handicap_taxonomy = (
        "TWO_WAY_NO_DRAW" if family == "HANDICAP_EUROPEAN" and handicap_kind == "TWO_WAY" else
        "EUROPEAN_THREE_WAY_WITH_DRAW" if family == "HANDICAP_EUROPEAN" and handicap_kind == "THREE_WAY" else
        ""
    )
    if settlement == "UNKNOWN":
        settlement = _settlement_for(family, line, handicap_kind, selection)

    odd_rec = {
        "CATEGORY": category,
        "MAIN_TAB": main_tab or category,
        "MARKET_INSTANCE_ID": market_instance_id,
        "FAMILY": family,
        "MARKET": market_title,
        "PERIOD": period,
        "PERIOD_SOURCE": period_source,
        "PERIOD_CONFIDENCE": period_confidence,
        "PERIOD_HINT": period_hint,
        "MARKET_SCOPE": market_scope,
        "OWNER": owner,
        "SELECTION": selection,
        "LINE": line,
        "SCORER_SCOPE": scorer_scope_value,
        "COLUMN_ROLE": column_role,
        "COLUMN_SEMANTICS_STATUS": column_semantics_status,
        "PARTICIPANT": participant,
        "PARTICIPANTS": participants,
        "TEAM_OWNER_STATUS": team_owner_status,
        "SETTLEMENT_SCOPE": market_scope,
        "HANDICAP_KIND": handicap_kind,
        "HANDICAP_TAXONOMY": handicap_taxonomy,
        "SETTLEMENT": settlement,
        "NAME_ALIAS_STATUS": alias_status,
        "ODDS": odds_str,
        "RAW": raw_text,
        "CONTAINER_ID": container_id,
        "run_id": run_id, "event_id": event_id, "source_hash": source_hash,
        "raw_record_id": raw_record_id,
        "source_raw_record_ids": list(source_raw_record_ids or ([raw_record_id] if raw_record_id else [])),
    }

    xtra_title = _contract_text(market_title)
    xtra_events = {
        "strzelec - xtra wygrana": "PLAYER_GOALS_GE_1",
        "zawodnik zaliczy asyste - xtra wygrana": "PLAYER_ASSISTS_GE_1",
        "zawodnik strzeli gola lub zaliczy asyste - xtra wygrana": "PLAYER_GOALS_PLUS_ASSISTS_GE_1",
    }
    if xtra_title in xtra_events:
        # The captured title declares an event, not a complete payout contract.
        # In particular its quoted odds must never imply ordinary binary payout.
        odd_rec.update(DECLARED_WINNING_EVENT=xtra_events[xtra_title],
                       WINNING_EVENT_SOURCE="CAPTURED_MARKET_TITLE_ONLY",
                       PAYOUT_CONTRACT="UNKNOWN", SETTLEMENT="UNKNOWN",
                       CONTRACT_MISSING="PAYOUT_FORMULA,PARTICIPATION,SUBSTITUTE,REFUND,HISTORICAL_RULE_APPLICABILITY")
    elif "xtra wygrana" in xtra_title:
        # Match-level and unrecognised Xtra variants are also special payouts.
        # A family/side classification does not prove ordinary WIN_LOSE terms.
        odd_rec.update(PAYOUT_CONTRACT="UNKNOWN", SETTLEMENT="UNKNOWN",
                       CONTRACT_MISSING="WINNING_EVENT,PAYOUT_FORMULA,REFUND,HISTORICAL_RULE_APPLICABILITY")
    return odd_rec, None


def headerless_top_card_exclusion(selection: str, tab_name: str, market_instance_id: str) -> dict[str, str] | None:
    """A proven Top card with an unaudited sentence: an explicit exclusion.

    The capture of the card is complete (price and text are both read); only
    its betting semantics are unknown.  It is therefore an accounted semantic
    exclusion, not a capture gap.  Rows outside the Top card boundary stay
    MISSING_MARKET_HEADER.
    """
    text = " ".join(str(selection or "").split())
    if not text or not is_top_offer_card(tab_name, market_instance_id):
        return None
    return {"market_title": UNRECOGNIZED_TOP_CARD_TITLE, "raw_selection": text, "unrecognized_top_card": "1"}


def neutralize_unrecognized_top_card(record: dict) -> dict:
    """Never let free text of an unknown card acquire a family, period or line."""
    record.update({"FAMILY": "GENERIC", "PERIOD": "UNKNOWN", "SETTLEMENT": "UNKNOWN", "OWNER": "",
                   "LINE": "", "PARTICIPANT": "", "UNRECOGNIZED_TOP_CARD": True})
    return record
