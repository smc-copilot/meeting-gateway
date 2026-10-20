#!/usr/bin/env python3
"""内部系统事件接收样例。只绑定回环地址；由现有 HTTPS 反向代理暴露 /meeting-events。"""
import argparse
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sqlite3
import time
from call import private_write


def verify(raw, headers, secret, now=None):
    now=time.time() if now is None else now
    h={k.lower():v for k,v in headers.items()}
    try:
        stamp=h['x-meeting-timestamp'];nonce=h['x-meeting-nonce']
        if abs(now-int(stamp))>300 or not 1<=len(nonce)<=128:raise ValueError()
        expected='sha256='+hmac.new(secret.encode(),stamp.encode()+b'.'+nonce.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,h['x-meeting-signature']):raise ValueError()
        obj=json.loads(raw)
        if not isinstance(obj,dict) or obj.get('event_id')!=h['x-meeting-event-id'] or not obj.get('event_id'):raise ValueError()
        return obj
    except (KeyError,ValueError,TypeError):raise ValueError('EVENT_VERIFICATION_FAILED') from None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--secret-file',required=True)
    p.add_argument('--port',type=int,default=9099)
    p.add_argument('--db',default='private/events.sqlite3')
    p.add_argument('--evidence',default='evidence/events')
    a=p.parse_args()
    Path(a.db).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    db=sqlite3.connect(a.db)
    db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, digest TEXT NOT NULL)');db.commit()
    __import__('os').chmod(a.db,0o600)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path!='/meeting-events':self.send_error(404);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>1048576:raise ValueError()
                self.connection.settimeout(5)
                raw=self.rfile.read(size)
                obj=verify(raw,dict(self.headers),Path(a.secret_file).read_text().strip())
                fingerprint=hashlib.sha256(raw).hexdigest()
                old=db.execute('SELECT digest FROM events WHERE id=?',(obj['event_id'],)).fetchone()
                if old and old[0]!=fingerprint:self.send_error(409);return
                duplicate=old is not None
                if not duplicate:
                    db.execute('INSERT INTO events VALUES (?,?)',(obj['event_id'],fingerprint));db.commit()
                receipt={'timestamp':datetime.now(timezone.utc).isoformat(),'status':'RECEIVED_SIGNATURE_VALID',
                         'event_id':obj['event_id'],'event_type':obj.get('event_type'),'resource_id':obj.get('resource_id'),
                         'body_sha256':fingerprint,'duplicate':duplicate}
                filename=hashlib.sha256(str(obj['event_id']).encode()).hexdigest()+'.json'
                private_write(Path(a.evidence)/filename,json.dumps(receipt,ensure_ascii=False,indent=2).encode())
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'OK')
            except Exception:
                self.send_error(400,'Event rejected')
    print('Listening on 127.0.0.1:'+str(a.port)+' /meeting-events; no credential output')
    try:HTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
    finally:db.close()
if __name__=='__main__':main()
