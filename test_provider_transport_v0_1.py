import json,tempfile,unittest
from pathlib import Path
from provider_transport_v0_1 import *
from identity_bridge_v0_1 import build_provider_derived_bridge
H='{"matchId":"42","externalMatchRef":"7","externalSportRef":"1"}'
B=build_provider_derived_bridge("42",H,"capture")
F=b'\x00\x00\x00\x00\x03abc\x80\x00\x00\x00\x00'
class AutoFinishContext:
 def on(self,event,handler):
  if event=='response': self.handler=lambda response:(handler(response),self.finished(response.request))
  elif event=='requestfinished': self.finished=handler
class TransportTests(unittest.TestCase):
 def test_l08_listener_error_preserves_redacted_message(self):
  class C(AutoFinishContext): pass
  class Q:
   post_data_buffer=b''; method='POST'; headers={}
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={}
   def body(self): raise RuntimeError('Authorization: Bearer top-secret body unavailable')
  c=C(); l=PassiveBetclicTransportListener(c,run_id='r',source_page_url='https://x',route_event_id='42'); c.handler(R())
  self.assertEqual(l.errors,['RuntimeError: Authorization=<redacted> body unavailable'])
  self.assertEqual(format_transport_exception(RuntimeError('Cookie: session-value transport failed')),'RuntimeError: Cookie=<redacted> transport failed')
  self.assertNotIn('top-secret',safe_transport_url('https://x/path?access_token=top-secret&ok=1#ignored'))
  self.assertIn('ok=1',safe_transport_url('https://x/path?access_token=top-secret&ok=1'))
  self.assertNotIn('client-secret',safe_transport_url('https://x/path?client_secret=client-secret&password=password-secret'))
  self.assertNotIn('client-secret',format_transport_exception(RuntimeError('client_secret=client-secret failed')))
  self.assertNotIn('hyphen-secret',json.dumps(safe_headers({'Client-Secret':'hyphen-secret','X-Test':'ok'})))
  self.assertNotIn('hyphen-secret',safe_transport_url('https://x/path?client-secret=hyphen-secret'))
  self.assertNotIn('hyphen-secret',format_transport_exception(RuntimeError('client-secret: hyphen-secret failed')))
 def test_l09_listener_errors_are_persisted_to_diagnostics(self):
  from core import log_provider_transport_listener_errors,log_provider_transport_flush_summary
  class D:
   def __init__(self): self.messages=[]
   def log(self,message): self.messages.append(message)
  class L: errors=['RuntimeError: Authorization=<redacted> body unavailable']; last_flush_summary={'REJECTED_BODY_CAPTURE_FAILED':1}
  diagnostics=D(); log_provider_transport_listener_errors(diagnostics,L())
  log_provider_transport_flush_summary(diagnostics,L())
  self.assertEqual(diagnostics.messages,['HISTORY_PROVIDER_TRANSPORT_V0_1_LISTENER_ERROR:RuntimeError: Authorization=<redacted> body unavailable','HISTORY_PROVIDER_TRANSPORT_V0_1_RECEIPT_SUMMARY={"REJECTED_BODY_CAPTURE_FAILED":1}'])
 def test_l10_body_capture_failure_has_a_durable_exact_bridge_receipt(self):
  class C(AutoFinishContext): pass
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08*'; method='POST'; headers={'content-type':'application/grpc-web+proto','x-request-id':'request-42'}; resource_type='fetch'
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification?access_token=secret'; status=200; request=Q(); headers={'content-type':'application/grpc-web+proto','x-request-id':'response-42'}
   def body(self): raise RuntimeError('Bearer secret-response body unavailable')
  c=C(); listener=PassiveBetclicTransportListener(c,run_id='r',source_page_url='https://x?token=source-secret',route_event_id='42'); c.handler(R())
  with tempfile.TemporaryDirectory() as d:
   self.assertEqual(listener.flush(Path(d),B),[])
   receipts=list(Path(d).glob('provider_transport_receipt_*.json'))
   self.assertEqual(len(receipts),1)
   receipt=json.loads(receipts[0].read_text())
  self.assertEqual(receipt['provider_event_id'],'42')
  self.assertEqual(receipt['request_match_id'],'42')
  self.assertEqual(receipt['filter_decision'],'REJECTED_BODY_CAPTURE_FAILED')
  self.assertEqual(receipt['rejection_reason'],'RESPONSE_BODY_UNAVAILABLE')
  self.assertEqual(receipt['body_capture_status'],'FAILED')
  self.assertIn('Bearer <redacted>',receipt['body_capture_error'])
  self.assertEqual(receipt['request_id'],'request-42')
  self.assertEqual(receipt['response_id'],'response-42')
  self.assertNotIn('secret',json.dumps(receipt))
 def test_l11_foreign_request_id_is_durable_rejection_not_silent_zero(self):
  class C(AutoFinishContext): pass
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08+'; method='POST'; headers={'content-type':'application/grpc-web+proto'}; resource_type='fetch'
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={'content-type':'application/grpc-web+proto'}
   def body(self): return F
  c=C(); listener=PassiveBetclicTransportListener(c,run_id='r',source_page_url='https://x',route_event_id='42'); c.handler(R())
  with tempfile.TemporaryDirectory() as d:
   self.assertEqual(listener.flush(Path(d),B),[])
   receipt=json.loads(next(Path(d).glob('provider_transport_receipt_*.json')).read_text())
  self.assertEqual(receipt['request_match_id'],'43')
  self.assertEqual(receipt['filter_decision'],'REJECTED_REQUEST_EVENT_ID_MISMATCH')
  self.assertEqual(receipt['rejection_reason'],'FOREIGN_PROVIDER_EVENT_ID')
  self.assertEqual(listener.last_flush_summary,{'REJECTED_REQUEST_EVENT_ID_MISMATCH':1})
 def test_l12_exact_captured_response_has_an_acceptance_receipt_and_raw_artifact(self):
  class C(AutoFinishContext): pass
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08*'; method='POST'; headers={'content-type':'application/grpc-web+proto'}; resource_type='fetch'
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={'content-type':'application/grpc-web+proto'}
   def body(self): return F
  c=C(); listener=PassiveBetclicTransportListener(c,run_id='r',source_page_url='https://x',route_event_id='42'); c.handler(R())
  with tempfile.TemporaryDirectory() as d:
   written=listener.flush(Path(d),B)
   receipt=json.loads(next(Path(d).glob('provider_transport_receipt_*.json')).read_text())
  self.assertEqual(len(written),1)
  self.assertEqual(receipt['filter_decision'],'ACCEPTED_FOR_PERSISTENCE')
  self.assertIsNone(receipt['rejection_reason'])
  self.assertEqual(listener.last_flush_summary,{'ACCEPTED_FOR_PERSISTENCE':1})
 def test_l13_foreign_id_remains_visible_when_its_body_capture_also_fails(self):
  class C(AutoFinishContext): pass
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08+'; method='POST'; headers={'content-type':'application/grpc-web+proto'}; resource_type='fetch'
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={'content-type':'application/grpc-web+proto'}
   def body(self): raise RuntimeError('body unavailable')
  c=C(); listener=PassiveBetclicTransportListener(c,run_id='r',source_page_url='https://x',route_event_id='42'); c.handler(R())
  with tempfile.TemporaryDirectory() as d:
   listener.flush(Path(d),B)
   receipt=json.loads(next(Path(d).glob('provider_transport_receipt_*.json')).read_text())
  self.assertEqual(receipt['filter_decision'],'REJECTED_REQUEST_EVENT_ID_MISMATCH')
  self.assertEqual(receipt['body_capture_status'],'FAILED')
  self.assertEqual(receipt['rejection_reason'],'FOREIGN_PROVIDER_EVENT_ID')
 def test_l14_standard_grpc_web_is_accepted_after_response_finishes(self):
  self.assertTrue(is_grpc_web_binary_content_type('application/grpc-web'))
  self.assertTrue(is_grpc_web_binary_content_type('application/grpc-web+proto; charset=utf-8'))
  self.assertFalse(is_grpc_web_binary_content_type('application/grpc-web+json'))
  class C(AutoFinishContext): pass
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08*'; method='POST'; headers={'content-type':'application/grpc-web+proto'}; resource_type='fetch'
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={'content-type':'application/grpc-web'}
   def body(self): return F
  c=C(); listener=PassiveBetclicTransportListener(c,run_id='r',source_page_url='https://x',route_event_id='42'); c.handler(R())
  with tempfile.TemporaryDirectory() as d: self.assertEqual(len(listener.flush(Path(d),B)),1)
  self.assertEqual(listener.observations[0]['body_capture_status'],'CAPTURED')
 def test_l15_body_capture_is_deferred_until_requestfinished(self):
  class C:
   def __init__(self): self.handlers={}
   def on(self,event,handler): self.handlers[event]=handler
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08*'; method='POST'; headers={'content-type':'application/grpc-web+proto'}; resource_type='fetch'
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={'content-type':'application/grpc-web'}
   def body(self): return F
  context=C(); listener=PassiveBetclicTransportListener(context,run_id='r',source_page_url='https://x',route_event_id='42'); response=R()
  context.handlers['response'](response)
  self.assertEqual(listener.observations[0]['body_capture_status'],'PENDING')
  context.handlers['requestfinished'](response.request)
  self.assertEqual(listener.observations[0]['body_capture_status'],'CAPTURED')
  self.assertEqual(listener._pending,{})
  with tempfile.TemporaryDirectory() as d: self.assertEqual(len(listener.flush(Path(d),B)),1)
 def test_l16_drain_waits_only_for_an_already_observed_target_request(self):
  class C:
   def __init__(self): self.handlers={}
   def on(self,event,handler): self.handlers[event]=handler
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08*'; method='POST'; headers={'content-type':'application/grpc-web+proto'}; resource_type='fetch'
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={'content-type':'application/grpc-web'}
   def body(self): return F
  context=C(); listener=PassiveBetclicTransportListener(context,run_id='r',source_page_url='https://x',route_event_id='42'); response=R(); context.handlers['response'](response)
  class Page:
   def __init__(self): self.waits=[]
   def wait_for_timeout(self,milliseconds): self.waits.append(milliseconds); context.handlers['requestfinished'](response.request)
  page=Page()
  self.assertEqual(listener.drain(page,25),0)
  self.assertEqual(page.waits,[25])
  self.assertEqual(listener.observations[0]['body_capture_status'],'CAPTURED')
 def test_p03_p04_p05_p06_frames_are_lossless_and_fail_closed(self):
  self.assertEqual([(x['is_trailer'],x['payload']) for x in parse_grpc_web_frames(F)],[(False,b'abc'),(True,b'')])
  for b in (b'\x00',b'\x00\x00\x00\x00\x04abc'):
   with self.assertRaises(TransportValidationError):parse_grpc_web_frames(b)
 def test_p01_p02_p07_p08_p09_p17_transport_is_bound_and_secret_safe(self):
  with tempfile.TemporaryDirectory() as d:
   r=write_transport_append_only(Path(d),run_id='r',source_page_url='https://x?token=source-secret',bridge=B,response_body=F,request_url='https://a?access_token=request-secret',response_status=200,response_headers={'Cookie':'bad','X-Test':'ok'})
   metadata=r['metadata'].read_text().lower()
   self.assertEqual(r['raw_response'].read_bytes(),F); self.assertNotIn('cookie',metadata); self.assertNotIn('source-secret',metadata); self.assertNotIn('request-secret',metadata); self.assertIn('x-test',metadata)
  with self.assertRaises(TransportValidationError):write_transport_append_only(Path(tempfile.gettempdir()),run_id='r',source_page_url='x',bridge={**B,'upstream_event_id':'8'},response_body=F,request_url='x',response_status=200)
  with self.assertRaises(TransportValidationError):write_transport_append_only(Path(tempfile.gettempdir()),run_id='r',source_page_url='x',bridge={**B,'bridge_sha256':'0'*64},response_body=F,request_url='x',response_status=200)
 def test_l01_l02_l06_l07_listener_filters_by_endpoint_content_type_and_request_id(self):
  class C(AutoFinishContext): pass
  class Q:
   post_data_buffer=b'\x00\x00\x00\x00\x02\x08*'; method='POST'; headers={'content-type':'application/grpc-web+proto'}
  class R:
   url='https://x/offering.access.api/offering.access.api.MatchService/GetMatchWithNotification'; status=200; request=Q(); headers={'content-type':'application/grpc-web+proto'}
   def body(self): return F
  c=C(); l=PassiveBetclicTransportListener(c,run_id='r',source_page_url='https://x',route_event_id='42'); c.handler(R())
  self.assertEqual(l.errors,[]); self.assertEqual(len(l.candidates),1)
  with tempfile.TemporaryDirectory() as d: self.assertEqual(len(l.flush(Path(d),B)),1)
  R.request.post_data_buffer=b'\x00\x00\x00\x00\x02\x08+'; c.handler(R())
  with tempfile.TemporaryDirectory() as d: self.assertEqual(len(l.flush(Path(d),B)),1)
