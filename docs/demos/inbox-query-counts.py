#!/usr/bin/env python3
"""Count actual HTTP queries for a private, temporary inbox lifecycle.

Run on either source checkout with PYTHONPATH=. python docs/demos/inbox-query-counts.py
--server /path/to/existing/quipu-server. The binary is not built or downloaded.
The temporary HOME, graph and store never use production signing credentials.
"""
import collections,contextlib,json,os,socket,subprocess,tempfile,threading,time,hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from shantytown.sd import SdTracker
from shantytown.inbox import TrackerInbox
from shantytown.query_identity import declared_command
import argparse
parser=argparse.ArgumentParser(description='Private loopback inbox lifecycle query counter; no production access')
parser.add_argument('--server', required=True, help='existing local quipu-server binary')
SERVER=str(Path(parser.parse_args().server).resolve(strict=True))
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
with tempfile.TemporaryDirectory(prefix='dnw-inbox-private-') as root:
 p=Path(root); (p/'.seeds').mkdir(); (p/'.seeds/config.toml').write_text('[project]\nprefix = \"sd\"\ngraph = \"https://example.test/project/dnw\"\n'); upstream='http://127.0.0.1:'+str(port()); pp=port();url='http://127.0.0.1:'+str(pp)
 env={k:v for k,v in os.environ.items() if not k.startswith(('QUIPU','SHANTY','ST_','SEEDS','BR_','GT_'))}
 env.update(HOME=root,XDG_CONFIG_HOME=root+'/config',XDG_DATA_HOME=root+'/data',XDG_CACHE_HOME=root+'/cache')
 os.environ.clear();os.environ.update(env)
 requests=[];trackers=[];phase='startup'
 class Proxy(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_GET(self):self.forward()
  def do_POST(self):self.forward()
  def forward(self):
   body=self.rfile.read(int(self.headers.get('Content-Length','0')))
   requests.append({'phase':phase,'path':self.path,'source':self.headers.get('X-Quipu-Source'),'operation':self.headers.get('X-Quipu-Operation'),'body_sha256':hashlib.sha256(body).hexdigest()})
   headers={k:v for k,v in self.headers.items() if k.lower() not in ('host','content-length','connection')}
   try:
    with urlopen(Request(upstream+self.path,data=body if self.command=='POST' else None,headers=headers,method=self.command),timeout=20) as r:out=r.read();code=r.status;ctype=r.headers.get('Content-Type','application/json')
   except HTTPError as e:out=e.read();code=e.code;ctype='application/json'
   self.send_response(code);self.send_header('Content-Type',ctype);self.end_headers();self.wfile.write(out)
 proxy=ThreadingHTTPServer(('127.0.0.1',pp),Proxy);thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
 log=(p/'server.log').open('w')
 child=subprocess.Popen([SERVER,'--db',str(p/'q.db'),'--bind',upstream.removeprefix('http://')],cwd=root,env=env,stdout=log,stderr=log)
 def box():
  t=SdTracker(repo=root,quipu=url,prefix='sd');trackers.append(t)
  return TrackerInbox(t,lambda:[],items_for=t.inbox_items),t
 try:
  for _ in range(100):
   try:urlopen(upstream+'/health',timeout=.2).close();break
   except OSError:
    if child.poll() is not None:raise RuntimeError('private server exited')
    time.sleep(.1)
  else:raise RuntimeError('private server health timeout')
  with declared_command('inbox'):
   phase='deliver';b,t=box();msg=b.deliver('worker','private-marker body',frm='reviewer')
   phase='unread';b,t=box();unread=b.unread('worker');assert len(unread)==1 and unread[0].id==msg.id and unread[0].body=='private-marker body'
   phase='receipt';b,t=box();assert b.find_delivery('worker','private-marker').id==msg.id
   phase='ack';b,t=box();marked=b.mark_read('worker',ids=[msg.id]);assert len(marked)==1 and marked[0].id==msg.id
   phase='closed-receipt';b,t=box();receipt=b.find_delivery('worker','private-marker');assert receipt.id==msg.id and receipt.read
   phase='empty-read';b,t=box();assert b.unread('worker')==[]
  counts={}
  for item in requests:
   if item['path']=='/query':counts[item['phase']]=counts.get(item['phase'],0)+1
  print(json.dumps({'queries_by_phase':counts,'total_queries':sum(counts.values()),'durable_positive':'deliver/read/exactreceipt/ack/closedreceipt/empty pass','format_diagnostics':[{'proof':vars(t._proof) if t._proof else None,'native':t._native_projection} for t in trackers],'request_metadata':requests},indent=2))
 finally:
  proxy.shutdown();proxy.server_close();thread.join();child.terminate();child.wait(timeout=10);log.close()
