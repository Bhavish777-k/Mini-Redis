#!/usr/bin/env python3
"""Phase 11, isolated-cluster integration: pagination, TTL, browser CRUD and failover.

Usage: python3 tests/test_key_browser_phase11.py ./build-debug/cluster-manager ./build-debug/fast-kv
Requires router 7001 and ports 6381/7381 free. No changes to your saved cluster-data.
"""
import http.client
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dashboard.app import Controller, Handler, HOST, wire

def check(value, message):
    assert value, message
    print('PASS:',message,flush=True)

def request(port, path, data, token=None):
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=12)
    headers={'Content-Type':'application/json'}
    if token is not None: headers['X-CSRF-Token']=token
    conn.request('POST',path,body=json.dumps(data),headers=headers)
    reply=conn.getresponse(); body=json.loads(reply.read()); status=reply.status
    conn.close()
    return status,body

def main():
    if len(sys.argv)!=3: raise SystemExit('Usage: test_key_browser_phase11.py MANAGER NODE')
    manager,node=[Path(x).resolve() for x in sys.argv[1:]]
    for port in (7001,6381,7381):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1',port))==0:
                raise SystemExit('Port %s busy — stop dashboard cluster first'%port)
    with tempfile.TemporaryDirectory(prefix='fastkv-browser-test-') as tmp:
        root=Path(tmp);(root/'dashboard').mkdir();(root/'build-debug').mkdir()
        shutil.copy2(manager,root/'build-debug/cluster-manager');shutil.copy2(node,root/'build-debug/fast-kv')
        ctl=Controller(root)
        server=ThreadingHTTPServer((HOST,0),Handler);server.controller=ctl
        port=server.server_port
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            status,body=request(port,'/api/keys/scan',{'cursor':'-','limit':10})
            check(status==403, 'browser mutations and reads require CSRF token')
            token=ctl.token
            cfg={'capacity':4096,'max_nodes':3,'threshold':60,'replicas':1}
            check(ctl.start(cfg)['online'], 'isolated replicated cluster started')
            _,body=request(port,'/api/keys/save',{'key':'session:00','value':'active','ttl_mode':'seconds','ttl_seconds':3600},token)
            check(body['ok'], 'create key with explicit TTL')
            _,body=request(port,'/api/keys/detail',{'key':'session:00'},token)
            check(body['data']['found'] and body['data']['value']=='active' and body['data']['ttl'] in range(3590,3601),'inspect value and remaining TTL')
            _,body=request(port,'/api/keys/expire',{'key':'session:00','ttl_mode':'never'},token)
            check(body['ok'] and wire('TTL session:00')=='-1','remove expiration without editing value')
            _,body=request(port,'/api/keys/expire',{'key':'session:00','ttl_mode':'seconds','ttl_seconds':1},token)
            check(body['ok'] and wire('TTL session:00') in ('0','1'),'change TTL without editing value')
            time.sleep(1.3)
            _,body=request(port,'/api/keys/detail',{'key':'session:00'},token)
            check(not body['data']['found'],'expired key hidden in detail')
            _,body=request(port,'/api/keys/scan',{'cursor':'-','prefix':'session:00','limit':10},token)
            check(body['data']['items']==[],'expired key hidden from browsing')
            # Force 2+ browse pages and automatic placement across shards.
            names=[f'session:{i:02d}' for i in range(1,27)]
            for key in names:
                code,res=request(port,'/api/keys/save',{'key':key,'value':'v'*110,'ttl_mode':'never'},token)
                assert code==200,(key,res)
            code,res=request(port,'/api/keys/scan',{'cursor':'-','prefix':'session:','limit':12},token)
            assert code==200,(code,res)
            got=[x['key'] for x in res['data']['items']];cursor=res['data']['next_cursor']
            check(len(got)==12 and cursor!='-','first SCAN page limited, cursor returned')
            while cursor!='-':
                code,res=request(port,'/api/keys/scan',{'cursor':cursor,'prefix':'session:','limit':12},token)
                assert code==200,(code,res)
                got.extend(x['key'] for x in res['data']['items']);cursor=res['data']['next_cursor']
            check(got==names,'SCAN sorted and complete across shards without duplicates')
            code,_=request(port,'/api/keys/save',{'key':'session:01','value':'x','ttl_mode':'never'},token)
            check(code==409,'unintended overwrite rejected')
            code,res=request(port,'/api/keys/save',{'key':'session:01','value':'updated','overwrite':True,'ttl_mode':'seconds','ttl_seconds':300},token)
            check(code==200 and wire('GET session:01')=='updated' and 0<=int(wire('TTL session:01'))<=300,'explicit edit and manual 5-minute TTL')
            code,_=request(port,'/api/keys/save',{'key':'bad key','value':'x','ttl_mode':'never'},token)
            check(code==409,'unsafe key rejected')
            code,_=request(port,'/api/keys/save',{'key':'too_many','value':'x','ttl_mode':'seconds','ttl_seconds':0},token)
            check(code==409,'invalid TTL rejected without write')
            code,_=request(port,'/api/keys/delete',{'key':'session:02','confirmation':'NO'},token)
            check(code==409,'delete requires exact-key confirmation')
            code,res=request(port,'/api/keys/delete',{'key':'session:02','confirmation':'session:02'},token)
            check(code==200 and res['data']['deleted'] and wire('WHERE session:02')=='(nil)','delete removes key')
            # Primary crash and router reorganization (using live owner from WHERE).
            before=wire('WHERE session:01');info=ctl.status();primary=next(n for n in info['nodes'] if str(n['port'])==before)
            import os, signal
            os.kill(int(primary['pid']),signal.SIGKILL)
            deadline=time.monotonic()+9
            while time.monotonic()<deadline:
                try:
                    if wire('GET session:01')=='updated' and wire('WHERE session:01')!=before:break
                except Exception:pass
                time.sleep(0.2)
            check(wire('WHERE session:01') != before, 'replica promoted after primary crash')
            code,res=request(port,'/api/keys/scan',{'cursor':'-','prefix':'session:01','limit':10},token)
            check(code==200 and [x['key'] for x in res['data']['items']]==['session:01'],'SCAN works after failover')
            print('ALL PHASE 11 KEY BROWSER TESTS PASSED',flush=True)
        finally:
            ctl.close();server.shutdown();server.server_close();thread.join(timeout=3)
if __name__=='__main__':main()
