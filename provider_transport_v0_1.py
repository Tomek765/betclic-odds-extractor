"""Lossless, append-only provider-response evidence for PATCH_C."""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from snapshot_manifest_v0_1 import canonical_json_bytes
from identity_bridge_v0_1 import validate_bridge_for_label, IdentityBridgeValidationError

SCHEMA_VERSION="APEX_PROVIDER_TRANSPORT_V0_1"
RECEIPT_SCHEMA_VERSION="APEX_PROVIDER_TRANSPORT_RECEIPT_V0_1"
SENSITIVE_HEADERS=frozenset({"authorization","cookie","set-cookie","x-api-key","x_api_key","proxy-authorization","proxy_authorization","token","access-token","access_token","id-token","id_token","api-key","api_key","client-secret","client_secret","x-client-secret","x_client_secret","password"})
_SENSITIVE_ERROR_VALUE=re.compile(r"(?i)\b(authorization|cookie|set-cookie|x[-_]api[-_]key|proxy[-_]authorization|token|access[-_]token|id[-_]token|api[-_]key|(?:x[-_]?)?client[-_]secret|password)\b\s*[:=]\s*(?:bearer\s+)?[^,\s;&]+")
_BEARER_VALUE=re.compile(r"(?i)\bbearer\s+[^,\s;&]+")
_SENSITIVE_QUERY_KEYS=SENSITIVE_HEADERS
class TransportValidationError(ValueError): pass

def format_transport_exception(exc:BaseException)->str:
    """Retain actionable listener diagnostics without retaining credentials."""
    message=_SENSITIVE_ERROR_VALUE.sub(lambda match:f"{match.group(1)}=<redacted>",str(exc))
    message=_BEARER_VALUE.sub("Bearer <redacted>",message).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

def safe_transport_url(url:str)->str:
    """Keep transport routing evidence without persisting query credentials."""
    parsed=urlsplit(str(url or ""))
    query=urlencode([(key, "<redacted>" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
                     for key,value in parse_qsl(parsed.query, keep_blank_values=True)])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))

def sha256_bytes(value:bytes)->str: return hashlib.sha256(value).hexdigest()

def is_grpc_web_binary_content_type(value:str|None)->bool:
    """Accept the two binary grpc-web media types used by the provider."""
    media_type=str(value or "").split(";",1)[0].strip().lower()
    return media_type in {"application/grpc-web","application/grpc-web+proto"}

def _utc_now()->str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")

def _safe_identifier(headers:dict[str,str]|None)->str|None:
    """Keep only correlation identifiers; credentials are never identifiers."""
    lowered={str(key).lower():str(value) for key,value in (headers or {}).items()}
    for key in ("x-request-id","x-correlation-id","traceparent","x-amzn-trace-id"):
        if lowered.get(key): return lowered[key]
    return None

def _validate_exact_bridge(bridge:dict[str,Any])->None:
    try:
        evidence=bridge["evidence"]
        if any(evidence.get(key)!=bridge.get(key) for key in ("provider_event_id","upstream_provider","upstream_event_id","upstream_sport_id")):
            raise IdentityBridgeValidationError("bridge fields conflict with frozen evidence")
        validate_bridge_for_label(bridge,bridge["provider_event_id"],bridge["upstream_provider"],bridge["upstream_event_id"],bridge.get("upstream_sport_id"))
    except (KeyError,IdentityBridgeValidationError) as exc:
        raise TransportValidationError("approved exact identity bridge required") from exc

def parse_grpc_web_frames(body:bytes)->list[dict[str,Any]]:
    """Parse binary grpc-web framing only; protobuf semantics stay opaque."""
    offset=0; frames=[]
    while offset<len(body):
        if len(body)-offset<5: raise TransportValidationError("truncated grpc-web frame header")
        flag=body[offset]; length=int.from_bytes(body[offset+1:offset+5],"big"); offset+=5
        if length>len(body)-offset: raise TransportValidationError("grpc-web frame length exceeds body")
        payload=body[offset:offset+length]; offset+=length
        frames.append({"is_trailer":bool(flag&0x80),"is_compressed":bool(flag&1),"payload":payload,
                       "payload_sha256":sha256_bytes(payload)})
    return frames

def safe_headers(headers:dict[str,str]|None)->dict[str,str]:
    return {str(k).lower():str(v) for k,v in (headers or {}).items() if str(k).lower() not in SENSITIVE_HEADERS}

def extract_request_match_id(request_body:bytes)->str|None:
    """Decode only the observed request shape: grpc frame / protobuf field 1 varint.

    Field meaning is constrained to this known MatchService request and is
    never applied to the response protobuf.
    """
    try: frames=parse_grpc_web_frames(request_body)
    except TransportValidationError: return None
    messages=[f["payload"] for f in frames if not f["is_trailer"] and not f["is_compressed"]]
    if len(messages)!=1 or not messages[0] or messages[0][0]!=8: return None
    value=0; shift=0
    for byte in messages[0][1:]:
        value|=(byte&127)<<shift
        if not byte&128: return str(value) if value else None
        shift+=7
        if shift>63: return None
    return None

class PassiveBetclicTransportListener:
    """Passive BrowserContext listener; buffers target responses until exact bridge exists."""
    TARGET="/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification"
    def __init__(self, context:Any, *, run_id:str, source_page_url:str, route_event_id:str|None):
        self.run_id,self.source_page_url,self.route_event_id=run_id,source_page_url,route_event_id
        self.candidates:list[dict[str,Any]]=[]; self.observations:list[dict[str,Any]]=[]; self.errors:list[str]=[]
        self._pending:dict[int,dict[str,Any]]={}
        self._sequence=0; self.last_flush_summary:dict[str,int]={}
        context.on("response",self._on_response)
        context.on("requestfinished",self._on_requestfinished)
    def _on_response(self,response:Any)->None:
        try:
            if self.TARGET not in response.url: return
            request=response.request
            request_body=request.post_data_buffer or b""
            self._sequence+=1
            observation={"listener_sequence":self._sequence,"observed_at":_utc_now(),"url":response.url,
              "status":response.status,"request_method":request.method,"request_content_type":request.headers.get("content-type"),
              "response_content_type":response.headers.get("content-type"),"response_headers":response.headers,
              "resource_type":getattr(request,"resource_type",None),"request_id":_safe_identifier(request.headers),
              "response_id":_safe_identifier(response.headers),"request_match_id":extract_request_match_id(request_body),
              "request_body_sha256":sha256_bytes(request_body),"body_capture_status":"PENDING","body_capture_error":None,
              "response_body_sha256":None,"response_completion_status":"NOT_AVAILABLE","response_completion_error":None}
            self.observations.append(observation)
            self._pending[id(request)]={"observation":observation,"response":response,"request_body":request_body}
        except Exception as exc: self.errors.append(format_transport_exception(exc))
    def _on_requestfinished(self,request:Any)->None:
        pending=self._pending.pop(id(request),None)
        if pending is None: return
        observation=pending["observation"]
        if observation["body_capture_status"] != "PENDING": return
        observation["response_completion_status"]="COMPLETED"
        try:
            body=pending["response"].body()
        except Exception as exc:
            error=format_transport_exception(exc)
            observation["body_capture_status"]="FAILED"; observation["body_capture_error"]=error
            self.errors.append(error)
            return
        observation["body_capture_status"]="CAPTURED"; observation["response_body_sha256"]=sha256_bytes(body)
        self.candidates.append({"listener_sequence":observation["listener_sequence"],"response_body":body,
          "request_body":pending["request_body"]})
    def drain(self,page:Any, timeout_ms:int)->int:
        """Give only already-observed target requests a bounded chance to finish."""
        pending=sum(item["body_capture_status"]=="PENDING" for item in self.observations)
        if pending and timeout_ms>0:
            page.wait_for_timeout(timeout_ms)
        return sum(item["body_capture_status"]=="PENDING" for item in self.observations)
    def flush(self,directory:Path,bridge:dict[str,Any],snapshot_id:str|None=None)->list[dict[str,Path]]:
        _validate_exact_bridge(bridge)
        written=[]; candidates={item["listener_sequence"]:item for item in self.candidates}; summary={}
        for observation in self.observations:
            candidate=candidates.get(observation["listener_sequence"])
            decision="ACCEPTED_FOR_PERSISTENCE"; reason=None
            if not is_grpc_web_binary_content_type(observation["response_content_type"]):
                decision,reason="REJECTED_RESPONSE_CONTENT_TYPE","UNEXPECTED_RESPONSE_CONTENT_TYPE"
            elif observation["request_match_id"] is None:
                decision,reason="REJECTED_REQUEST_EVENT_ID_UNAVAILABLE","REQUEST_EVENT_ID_UNPARSEABLE"
            elif observation["request_match_id"] != bridge.get("provider_event_id"):
                decision,reason="REJECTED_REQUEST_EVENT_ID_MISMATCH","FOREIGN_PROVIDER_EVENT_ID"
            elif observation["body_capture_status"] == "PENDING":
                decision,reason="REJECTED_RESPONSE_COMPLETION_UNOBSERVED","REQUEST_NOT_FINISHED"
            elif observation["body_capture_status"] != "CAPTURED":
                decision,reason="REJECTED_BODY_CAPTURE_FAILED","RESPONSE_BODY_UNAVAILABLE"
            else:
                try: parse_grpc_web_frames(candidate["response_body"])
                except TransportValidationError:
                    decision,reason="REJECTED_INVALID_GRPC_WEB_RESPONSE","INVALID_GRPC_WEB_FRAME"
            receipt={**observation,"filter_decision":decision,"rejection_reason":reason}
            write_transport_receipt_append_only(directory,run_id=self.run_id,source_page_url=self.source_page_url,bridge=bridge,snapshot_id=snapshot_id,receipt=receipt)
            summary[decision]=summary.get(decision,0)+1
            if decision == "ACCEPTED_FOR_PERSISTENCE":
                written.append(write_transport_append_only(directory,run_id=self.run_id,source_page_url=self.source_page_url,bridge=bridge,snapshot_id=snapshot_id,request_url=observation["url"],request_method=observation["request_method"],request_content_type=observation["request_content_type"],response_status=observation["status"],response_content_type=observation["response_content_type"],response_headers=observation["response_headers"],request_body=candidate["request_body"],response_body=candidate["response_body"]))
        self.last_flush_summary=summary
        return written

def write_transport_receipt_append_only(directory:Path, *, run_id:str, source_page_url:str, bridge:dict[str,Any],
                                        receipt:dict[str,Any], snapshot_id:str|None=None)->Path:
    """Write safe, append-only evidence for every observed target response.

    The listener records this evidence before reading the response body; flush
    writes it once an exact bridge is available. Raw response bytes remain
    separate and are written only after exact-ID and framing checks pass.
    """
    if not run_id or not isinstance(receipt.get("listener_sequence"),int) or receipt["listener_sequence"] < 1:
        raise TransportValidationError("run and listener sequence required")
    if not isinstance(receipt.get("status"),int) or not 100<=receipt["status"]<=599:
        raise TransportValidationError("response status required")
    _validate_exact_bridge(bridge)
    base={"schema_version":RECEIPT_SCHEMA_VERSION,"provider":"BETCLIC","provider_event_id":bridge["provider_event_id"],
      "external_provider":bridge["upstream_provider"],"external_event_id":bridge["upstream_event_id"],"external_sport_ref":bridge["upstream_sport_id"],
      "identity_bridge_sha256":bridge["bridge_sha256"],"run_id":run_id,"snapshot_id":snapshot_id,
      "listener_sequence":receipt["listener_sequence"],"response_observed_at":receipt.get("observed_at"),
      "request_url":safe_transport_url(receipt.get("url","")),"request_method":receipt.get("request_method"),
      "request_content_type":receipt.get("request_content_type"),"response_status":receipt["status"],
      "response_content_type":receipt.get("response_content_type"),"resource_type":receipt.get("resource_type"),
      "request_id":receipt.get("request_id"),"response_id":receipt.get("response_id"),"request_match_id":receipt.get("request_match_id"),
      "request_body_sha256":receipt.get("request_body_sha256"),"response_body_sha256":receipt.get("response_body_sha256"),
      "body_capture_status":receipt.get("body_capture_status"),"body_capture_error":receipt.get("body_capture_error"),
      "response_completion_status":receipt.get("response_completion_status"),"response_completion_error":receipt.get("response_completion_error"),
      "filter_decision":receipt.get("filter_decision"),"rejection_reason":receipt.get("rejection_reason"),
      "source_page_url":safe_transport_url(source_page_url)}
    artifact_id=hashlib.sha256(canonical_json_bytes(base)).hexdigest(); directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"provider_transport_receipt_{artifact_id}.json"
    with path.open("x",encoding="utf-8",newline="\n") as handle:
        json.dump({**base,"artifact_id":artifact_id},handle,sort_keys=True,separators=(",",":")); handle.write("\n")
    return path

def write_transport_append_only(directory:Path, *, run_id:str, source_page_url:str, bridge:dict[str,Any],
                                response_body:bytes, request_body:bytes=b"", request_url:str,
                                request_method:str="POST", request_content_type:str|None=None,
                                response_status:int, response_content_type:str|None=None,
                                response_headers:dict[str,str]|None=None,
                                snapshot_id:str|None=None, observed_at:str|None=None)->dict[str,Path]:
    if not run_id or not response_body or response_status<100 or response_status>599: raise TransportValidationError("run, response bytes and status required")
    _validate_exact_bridge(bridge)
    response_hash=sha256_bytes(response_body); request_hash=sha256_bytes(request_body)
    base={"schema_version":SCHEMA_VERSION,"provider":"BETCLIC","provider_event_id":bridge["provider_event_id"],"external_provider":bridge["upstream_provider"],"external_event_id":bridge["upstream_event_id"],"external_sport_ref":bridge["upstream_sport_id"],"identity_bridge_sha256":bridge["bridge_sha256"],"run_id":run_id,"snapshot_id":snapshot_id,"request_observed_at":observed_at,"response_observed_at":observed_at,"request_url":safe_transport_url(request_url),"request_method":request_method,"request_content_type":request_content_type,"response_status":response_status,"response_content_type":response_content_type,"transport_family":"GRPC_WEB_BINARY","raw_request_body_hash":request_hash,"raw_response_body_hash":response_hash,"source_page_url":safe_transport_url(source_page_url),"response_headers":safe_headers(response_headers)}
    artifact_id=hashlib.sha256(canonical_json_bytes(base)).hexdigest(); directory.mkdir(parents=True,exist_ok=True)
    raw=directory/f"provider_response_{artifact_id}.bin"; meta=directory/f"provider_transport_{artifact_id}.json"
    with raw.open("xb") as handle: handle.write(response_body)
    try:
        with meta.open("x",encoding="utf-8",newline="\n") as handle: json.dump({**base,"artifact_id":artifact_id,"raw_response_logical_path":raw.name},handle,sort_keys=True,separators=(",",":")); handle.write("\n")
    except Exception: raw.unlink(missing_ok=True); raise
    return {"metadata":meta,"raw_response":raw}
