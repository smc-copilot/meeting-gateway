import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

class ContractTests(unittest.TestCase):
    def load(self):
        self.assertTrue((ROOT / 'tools' / 'call.py').is_file(), '缺少 HTTP 调用脚本')
        import call
        return call

    def test_missing_field_must_not_equal_null(self):
        c = self.load()
        self.assertFalse(c.check_assertions({}, ['data.id=null'], [])[0]['matched'])

    def test_nested_match(self):
        c = self.load()
        self.assertTrue(c.check_assertions({'data': {'status':'ACTIVE'}}, ['data.status=ACTIVE'], [])[0]['matched'])

    def test_type_strict_bool(self):
        c = self.load()
        self.assertFalse(c.check_assertions({'database':1}, ['database=true'], [])[0]['matched'])

    def test_nonempty(self):
        c = self.load()
        self.assertFalse(c.check_assertions({'data': {'items':[]}}, [], ['data.items'])[0]['matched'])

    def test_http202_is_accepted_not_passed(self):
        c = self.load()
        self.assertEqual(c.classify(202, {202}, []), 'ACCEPTED')

    def test_business_failure(self):
        c = self.load()
        self.assertEqual(c.classify(200, {200}, c.check_assertions({'data': {'status':'FAILED'}}, ['data.status=PASSED'], [])), 'FAILED')

    def test_path_no_absolute_target(self):
        c = self.load()
        with self.assertRaises(ValueError): c.make_url('https://gateway.example.org', '//evil.example.org/a', False)

    def test_https_default(self):
        c = self.load()
        with self.assertRaises(ValueError): c.make_url('http://gateway.example.org', '/health/ready', False)

    def test_no_credentials_in_url(self):
        c = self.load()
        with self.assertRaises(ValueError): c.make_url('https://name:pw@gateway.example.org', '/a', False)

    def test_secret_assertion_rejected(self):
        c = self.load()
        with self.assertRaises(ValueError): c.check_assertions({}, ['data.access_token=secret-value'], [])

    def test_event_signature(self):
        self.assertTrue((ROOT/'tools'/'event_receiver.py').is_file(), '缺少回调校验脚本')
        import event_receiver as e
        import hmac, hashlib
        raw=b'{"event_id":"a","event_type":"meeting.asset.ready"}'
        signature=hmac.new(b'key', b'1000.nonce.'+raw, hashlib.sha256).hexdigest()
        headers={'X-Meeting-Timestamp':'1000','X-Meeting-Nonce':'nonce','X-Meeting-Signature':'sha256='+signature,'X-Meeting-Event-ID':'a'}
        self.assertEqual(e.verify(raw,headers,'key',now=1000)['event_id'],'a')
        with self.assertRaises(ValueError): e.verify(raw+b' ',headers,'key',now=1000)
        with self.assertRaises(ValueError): e.verify(raw,headers,'key',now=1400)

    def test_empty_report_blocked(self):
        self.assertTrue((ROOT/'tools'/'report.py').is_file(), '缺少报告脚本')
        import report
        self.assertEqual(report.gate(['A'],{}), 'BLOCKED')

    def test_accepted_report_blocked(self):
        self.assertTrue((ROOT/'tools'/'report.py').is_file(), '缺少报告脚本')
        import report
        self.assertEqual(report.gate(['A'],{'A': {'status':'ACCEPTED'}}), 'BLOCKED')

if __name__=='__main__': unittest.main()

class HttpTests(unittest.TestCase):
    def test_real_local_http_transport_and_redirect_rejection(self):
        import threading
        from http.server import BaseHTTPRequestHandler,HTTPServer
        import call
        events=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                events.append((self.path,self.headers.get('Authorization')))
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location','/target');self.end_headers();return
                body=b'{"database":true,"backend":true}'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            status,raw,_,_=call.perform(base,'/health/ready',token='unit-test-token',allow_http=True)
            self.assertEqual(status,200);self.assertTrue(json.loads(raw)['database'])
            status,_,_,_=call.perform(base,'/redirect',token='unit-test-token',allow_http=True)
            self.assertEqual(status,302);self.assertFalse(any(x[0]=='/target' for x in events))
        finally:server.shutdown();server.server_close();thread.join()
