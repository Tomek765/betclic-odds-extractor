"""PATCH_C exact-ID, append-only post-match outcome and event contracts."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from history_contract_v0_1 import canonicalize_utc_datetime
from snapshot_manifest_v0_1 import canonical_json_bytes

OUTCOME_SCHEMA="APEX_MATCH_OUTCOME_V0_1"; TIMELINE_SCHEMA="APEX_MATCH_EVENT_TIMELINE_V0_1"; LABEL_REVISION_SCHEMA="APEX_MATCH_LABEL_REVISION_V0_1"
FINAL_STATUSES=frozenset({"FINAL","AFTER_EXTRA_TIME","AFTER_PENALTIES"})
NON_SETTLED_STATUSES=frozenset({"LIVE","POSTPONED","ABANDONED","CANCELLED"})
EVENT_TYPES=frozenset({"GOAL","OWN_GOAL","RED_CARD","SECOND_YELLOW_RED","PENALTY_GOAL","PENALTY_MISS"})
class OutcomeValidationError(ValueError): pass
def _hash(value: Any)->str: return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
def _is_sha256(value:Any)->bool: return isinstance(value,str) and bool(re.fullmatch(r"[0-9a-f]{64}",value))
def build_outcome(provider_event_id:str, status:str, home_ft:int|None, away_ft:int|None, observed_at:str, source:dict[str,str], home_ht:int|None=None, away_ht:int|None=None)->dict[str,Any]:
    at=canonicalize_utc_datetime(observed_at)
    if not provider_event_id or not at or not isinstance(source,dict) or not isinstance(source.get("logical_path"),str) or not source["logical_path"] or not _is_sha256(source.get("sha256")): raise OutcomeValidationError("identity, time and source required")
    if status not in FINAL_STATUSES: raise OutcomeValidationError("not a trainable final status")
    if any(not isinstance(x,int) or x<0 for x in (home_ft,away_ft)): raise OutcomeValidationError("final scores required")
    if (home_ht is None)!=(away_ht is None) or any(x is not None and (not isinstance(x,int) or x<0) for x in (home_ht,away_ht)): raise OutcomeValidationError("HT scores must be paired non-negative ints")
    base={"schema_version":OUTCOME_SCHEMA,"provider_event_id":provider_event_id,"match_status":status,"home_score_ft":home_ft,"away_score_ft":away_ft,"home_score_ht":home_ht,"away_score_ht":away_ht,"outcome_observed_at":at,"outcome_source":source}
    return {**base,"outcome_hash":_hash(base)}
def build_event(provider_event_id:str, sequence:int, event_type:str, team_side:str, minute:int, observed_at:str, source:dict[str,str], stoppage_minute:int|None=None, event_time_exact:str|None=None)->dict[str,Any]:
    at=canonicalize_utc_datetime(observed_at); exact=canonicalize_utc_datetime(event_time_exact) if event_time_exact else None
    if not provider_event_id or not isinstance(sequence,int) or sequence<1 or event_type not in EVENT_TYPES or team_side not in {"HOME","AWAY","UNKNOWN"} or not isinstance(minute,int) or minute<0 or not at or not isinstance(source,dict) or not isinstance(source.get("logical_path"),str) or not source["logical_path"] or not _is_sha256(source.get("sha256")): raise OutcomeValidationError("invalid event")
    if stoppage_minute is not None and (not isinstance(stoppage_minute,int) or stoppage_minute<1): raise OutcomeValidationError("invalid stoppage minute")
    base={"schema_version":TIMELINE_SCHEMA,"provider_event_id":provider_event_id,"event_sequence":sequence,"event_type":event_type,"team_side":team_side,"match_minute":minute,"stoppage_minute":stoppage_minute,"event_time_exact":exact,"outcome_observed_at":at,"source":source}
    return {**base,"event_hash":_hash(base)}
def validate_outcome(outcome:dict[str,Any])->None:
    """Reject tampered final-state content before it can join a snapshot."""
    if not isinstance(outcome,dict): raise OutcomeValidationError("outcome must be an object")
    try:
        expected=build_outcome(outcome["provider_event_id"],outcome["match_status"],outcome["home_score_ft"],outcome["away_score_ft"],outcome["outcome_observed_at"],outcome["outcome_source"],outcome.get("home_score_ht"),outcome.get("away_score_ht"))
    except (KeyError,OutcomeValidationError) as exc:
        raise OutcomeValidationError("invalid outcome") from exc
    if set(outcome)!=set(expected) or outcome.get("outcome_hash")!=expected["outcome_hash"]:
        raise OutcomeValidationError("outcome hash does not match content")
def validate_event(event:dict[str,Any])->None:
    """Reject tampered timeline content before exact-ID acceptance."""
    if not isinstance(event,dict): raise OutcomeValidationError("event must be an object")
    try:
        expected=build_event(event["provider_event_id"],event["event_sequence"],event["event_type"],event["team_side"],event["match_minute"],event["outcome_observed_at"],event["source"],event.get("stoppage_minute"),event.get("event_time_exact"))
    except (KeyError,OutcomeValidationError) as exc:
        raise OutcomeValidationError("invalid event") from exc
    if set(event)!=set(expected) or event.get("event_hash")!=expected["event_hash"]:
        raise OutcomeValidationError("event hash does not match content")
def validate_exact_join(snapshot:dict[str,Any], outcome:dict[str,Any], events:list[dict[str,Any]])->None:
    validate_outcome(outcome)
    if not isinstance(events,list): raise OutcomeValidationError("events must be a list")
    for event in events: validate_event(event)
    event_id=snapshot.get("provider_event_id")
    if not event_id or outcome.get("provider_event_id")!=event_id or any(e.get("provider_event_id")!=event_id for e in events): raise OutcomeValidationError("exact provider_event_id join required")
    if len({e["event_sequence"] for e in events})!=len(events): raise OutcomeValidationError("duplicate event sequence")
    if [e["event_sequence"] for e in sorted(events,key=lambda e:e["event_sequence"])]!=list(range(1,len(events)+1)): raise OutcomeValidationError("timeline sequence gap")

def build_label_revision(provider_event_id:str, layer:str, payload_hash:str, revision:int,
                         observed_at:str, supersedes_hash:str|None=None,
                         availability:str="AVAILABLE")->dict[str,Any]:
    """Append-only outcome/timeline revision.  Timeline may be unavailable independently."""
    at=canonicalize_utc_datetime(observed_at)
    if (not provider_event_id or layer not in {"OUTCOME","TIMELINE"} or not _is_sha256(payload_hash)
            or not isinstance(revision,int) or revision<1 or not at
            or availability not in {"AVAILABLE","UNAVAILABLE","PARTIAL"}):
        raise OutcomeValidationError("invalid label revision")
    if revision==1 and supersedes_hash is not None: raise OutcomeValidationError("initial revision cannot supersede")
    if revision>1 and (not isinstance(supersedes_hash,str) or len(supersedes_hash)!=64):
        raise OutcomeValidationError("correction must name prior payload hash")
    base={"schema_version":LABEL_REVISION_SCHEMA,"provider_event_id":provider_event_id,"layer":layer,
          "payload_hash":payload_hash,"revision":revision,"supersedes_hash":supersedes_hash,
          "availability":availability,"observed_at":at}
    return {**base,"revision_hash":_hash(base)}

def validate_label_revision(revision:dict[str,Any])->None:
    """Reject forged revisions and any attempt to carry snapshot state forward."""
    if not isinstance(revision,dict) or {"snapshot_id","snapshot_sha256","canonical_snapshot"}&set(revision):
        raise OutcomeValidationError("label revision cannot contain snapshot state")
    try:
        expected=build_label_revision(revision["provider_event_id"],revision["layer"],revision["payload_hash"],revision["revision"],revision["observed_at"],revision.get("supersedes_hash"),revision["availability"])
    except (KeyError, OutcomeValidationError) as exc:
        raise OutcomeValidationError("invalid label revision") from exc
    if set(revision)!=set(expected) or revision.get("revision_hash")!=expected["revision_hash"]:
        raise OutcomeValidationError("label revision hash does not match content")

def write_label_revision_append_only(directory:Path, revision:dict[str,Any])->Path:
    """One immutable revision per content hash; no in-place correction is possible."""
    validate_label_revision(revision)
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"label_revision_{revision['revision_hash']}.json"
    with path.open("x",encoding="utf-8",newline="\n") as handle:
        json.dump(revision,handle,ensure_ascii=False,sort_keys=True,separators=(",",":")); handle.write("\n")
    return path

def label_eligibility(outcome:dict[str,Any]|None, timeline_availability:str)->dict[str,str]:
    """Outcome and timeline are independent gates; neither infers the other."""
    if outcome is not None: validate_outcome(outcome)
    outcome_ok=bool(outcome and outcome.get("match_status") in FINAL_STATUSES and
                    isinstance(outcome.get("home_score_ft"),int) and isinstance(outcome.get("away_score_ft"),int))
    if timeline_availability not in {"AVAILABLE","PARTIAL","UNAVAILABLE"}:
        raise OutcomeValidationError("invalid timeline availability")
    return {"OUTCOME_ELIGIBLE":"YES" if outcome_ok else "NO",
            "TIMELINE_ELIGIBLE":"YES" if outcome_ok and timeline_availability=="AVAILABLE" else "NO"}
