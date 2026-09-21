"""Fail-closed normalization of a provider-runtime decoded final response.

This module deliberately does not implement protobuf.  The response must first
be decoded by the provider's generated runtime and tied to lossless raw bytes.
The observed provider schema identifies ``ScoreboardStatus.ENDED`` as enum 3
and ``currentScore.contestant1/contestant2`` as the exact final score strings.
"""
from __future__ import annotations
from typing import Any
from outcome_timeline_v0_1 import OutcomeValidationError, build_outcome

PROVIDER_RESPONSE_TYPE="offering.access.api.GetMatchResponse"
SCOREBOARD_STATUS_ENDED=3

class ProviderFinalStateError(OutcomeValidationError): pass

def _score(value:Any)->int:
    if isinstance(value,bool) or not isinstance(value,(str,int)):
        raise ProviderFinalStateError("final score must be a decimal integer")
    text=str(value)
    if not text.isdecimal(): raise ProviderFinalStateError("final score must be a non-negative decimal integer")
    return int(text)

def normalize_final_response(*, expected_provider_event_id:str, decoded_evidence:dict[str,Any],
                             raw_source:dict[str,str], observed_at:str,
                             assignment_candidate_ids:list[str]|tuple[str,...])->dict[str,Any]:
    """Return an APEX outcome only for one exact, final, runtime-decoded match.

    ``decoded_evidence`` is the JSON result emitted by the provider-generated
    decoder and must retain the raw and schema hashes.  Candidate identity is
    explicit so a caller cannot silently choose one of several matches.
    """
    if not expected_provider_event_id or not isinstance(raw_source,dict):
        raise ProviderFinalStateError("exact identity and raw source required")
    if assignment_candidate_ids != [expected_provider_event_id]:
        raise ProviderFinalStateError("exactly one matching assignment required")
    if decoded_evidence.get("response_type") != PROVIDER_RESPONSE_TYPE:
        raise ProviderFinalStateError("unexpected generated response type")
    if decoded_evidence.get("raw_stream_sha256") != raw_source.get("sha256"):
        raise ProviderFinalStateError("decoded response is not tied to raw bytes")
    if not isinstance(decoded_evidence.get("schema_source_sha256"),str) or len(decoded_evidence["schema_source_sha256"]) != 64:
        raise ProviderFinalStateError("generated schema provenance required")
    try:
        response=decoded_evidence["decoded_response"]["response"]
        if response.get("oneofKind") != "payload": raise ProviderFinalStateError("missing response payload")
        match=response["payload"]["match"]
        scoreboard=match["scoreboard"]
    except (KeyError,TypeError) as exc:
        raise ProviderFinalStateError("missing final-state fields") from exc
    if str(match.get("matchId")) != expected_provider_event_id or str(scoreboard.get("matchId")) != expected_provider_event_id:
        raise ProviderFinalStateError("foreign provider event id")
    if match.get("isLive") is not False or scoreboard.get("liveDisplayStatus") != SCOREBOARD_STATUS_ENDED:
        raise ProviderFinalStateError("provider response is not final")
    score=scoreboard.get("currentScore")
    if not isinstance(score,dict): raise ProviderFinalStateError("missing final score")
    return build_outcome(expected_provider_event_id,"FINAL",_score(score.get("contestant1")),
                         _score(score.get("contestant2")),observed_at,raw_source)
