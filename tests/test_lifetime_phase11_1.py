#!/usr/bin/env python3
"""Isolated integration tests for developer TTL policy, SDKs and dashboard.

Run with cluster stopped: python3 tests/test_lifetime_phase11_1.py MANAGER FAST_KV
Uses a fresh temporary cluster-data directory; never touches user's saved data.
"""
import http.client
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'sdk/python/src'))
from fastkv import FastKV
from dashboard.app import Controller, Handler, HOST, wire
from dashboard.backup_ops import BackupError, create_backup


def request(port, path, payload, token):
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
    conn.request('POST',path,json.dumps(payload),{'Content-Type':'application/json','X-CSRF-Token':token})
    reply=conn.getresponse()
    code=reply.status
    content=json.loads(reply.read())
    conn.close()
    assert code==200,(path,code,content)
    return content['data']


def check(value, why):
    assert value, why
    print('PASS:',why,flush=True)


def main():
    if len(sys.argv)!=3: raise SystemExit('Usage: test_lifetime_phase11_1.py MANAGER FAST_KV')
    manager, node=(Path(arg).resolve() for arg in sys.argv[1:])
    for port in (7001,6381,7381):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',port))==0:
                raise SystemExit(f'Port {port} busy: stop your dashboard cluster first')
    with tempfile.TemporaryDirectory(prefix='fastkv-lifetime-dev-') as folder:
        root=Path(folder)
        (root/'build-debug').mkdir();(root/'dashboard').mkdir()
        shutil.copy2(manager,root/'build-debug/cluster-manager')
        shutil.copy2(node,root/'build-debug/fast-kv')
        ctl=Controller(root)
        web=ThreadingHTTPServer((HOST,0),Handler)
        web.controller=ctl
        th=threading.Thread(target=web.serve_forever,daemon=True);th.start()
        cfg={'capacity':8192,'max_nodes':2,'threshold':85,'replicas':1}
        db=FastKV()
        try:
            check(ctl.start(cfg)['online'],'isolated replicated cluster started')
            check(db.get_default_ttl() is None,'default policy initially never expire')
            out=request(web.server_port,'/api/ttl-policy',{'mode':'seconds','seconds':600},ctl.token)
            check(out['default_ttl']==600 and db.get_default_ttl()==600,'dashboard sets shared default TTL')
            check(db.set('sdk:default','v') and 0<=db.ttl('sdk:default')<=600,'Python SDK inherits database default')
            check(db.set('sdk:short','v',ttl=30) and 0<=db.ttl('sdk:short')<=30,'Python SDK explicit per-key TTL wins')
            check(db.set('sdk:permanent','v',persist=True) and db.ttl('sdk:permanent')==-1,'SDK explicit permanent wins')
            check(db.set('sdk:short','updated',keep_ttl=True) and 0<=db.ttl('sdk:short')<=30,'Editing a key can keep its absolute deadline')
            check(db.incr('counter:new')==1 and db.ttl('counter:new')>=0,'INCR-created keys inherit default')
            check(db.incr('counter:new')==2 and db.ttl('counter:new')>=0,'INCR preserves existing expiration')
            check(db.set('now','v',ttl=0) and db.get('now') is None,'EX 0 expires immediately')
            check(wire('SET bad x EX xx').startswith('ERR') and db.get('bad') is None,'invalid TTL rejected before write')
            check(request(web.server_port,'/api/keys/save',{'key':'web:default','value':'v','ttl_mode':'default'},ctl.token)['saved'] and db.ttl('web:default')>=0,'key browser inherits default')
            check(request(web.server_port,'/api/keys/save',{'key':'web:never','value':'v','ttl_mode':'never'},ctl.token)['saved'] and db.ttl('web:never')==-1,'key browser supports explicit never expire')
            check(request(web.server_port,'/api/key',{'action':'SET','key':'console:custom','value':'v','ttl_mode':'seconds','ttl_seconds':45},ctl.token)['reply']=='OK' and 0<=db.ttl('console:custom')<=45,'Key Console honors manual TTL')
            check(request(web.server_port,'/api/key',{'action':'SET','key':'console:default','value':'v','ttl_mode':'default'},ctl.token)['reply']=='OK' and db.ttl('console:default')>=0,'Key Console honors database default')
            js="""
const { FastKV } = require('./sdk/node');
(async()=>{
 const db=new FastKV();
 if(await db.getDefaultTTL()!==600)throw Error('default');
 await db.set('js:explicit','v',{ttl:90});
 await db.set('js:forever','v',{persist:true});
 await db.set('js:default','v');
 if(await db.ttl('js:explicit')<0||await db.ttl('js:forever')!==-1||await db.ttl('js:default')<0)throw Error('TTL mismatch');
 console.log('NODE_OK');
})().catch(e=>{console.error(e); process.exitCode=1;});
"""
            node_test=subprocess.run(['node','-e',js],cwd=ROOT,capture_output=True,text=True,timeout=10)
            check(node_test.returncode==0 and 'NODE_OK' in node_test.stdout, 'Node.js SDK uses same lifetime rules')
            check(db.set_default_ttl(1200) and 0<=db.ttl('sdk:default')<=600,'changing policy does not rewrite existing deadlines')
            check(db.set('newpolicy','v') and 0<=db.ttl('newpolicy')<=1200,'new writes receive updated default')
            check(ctl.stop()['stopped'],'stop cluster for policy durability check')
            check((root/'cluster-data/default_ttl.meta').read_text().strip()=='1200','default TTL stored in cluster-data')
            # A killed manager could leave an in-flight value+lifetime intent.
            until=int(time.time()*1000)+90000
            pending=root/'cluster-data/pending_lifetime_write'
            pending.write_text(f'"pending:key" "recovered" {until}\n')
            try:
                create_backup(root)
                raise AssertionError('Incomplete intent backup accepted')
            except BackupError:
                check(True,'offline backup rejects incomplete lifetime transaction')
            check(ctl.start(cfg)['online'],'restart replays interrupted lifetime write')
            check(db.get('pending:key')=='recovered' and 0<=db.ttl('pending:key')<=90 and not pending.exists(),'manager reconciles interrupted write with original deadline')
            check(ctl.stop()['stopped'],'stop after recovery before backup')
            backup=create_backup(root)
            with zipfile.ZipFile(root/'backups'/backup['name']) as archive:
                check(archive.read('cluster-data/default_ttl.meta').strip()==b'1200','offline backup contains lifetime policy')
            check(ctl.start(cfg)['online'],'restart cluster with saved metadata')
            check(db.get_default_ttl()==1200 and db.get('sdk:default')=='v','default lifetime and key values survive restart')
            check(0<=db.ttl('sdk:short')<=30 and db.ttl('sdk:permanent')==-1,'per-key deadlines survive restart unchanged')
            check(db.set_default_ttl(None) and db.get_default_ttl() is None,'developer can disable default TTL')
            check(db.set('post:disabled','v') and db.ttl('post:disabled')==-1,'no default means permanent keys')
            print('ALL PHASE 11.1 DEVELOPER LIFETIME TESTS PASSED',flush=True)
        finally:
            ctl.close();web.shutdown();web.server_close();th.join(timeout=3)

if __name__=='__main__':main()
