import os,sys,json,time,tempfile,socket,subprocess,threading,shutil
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from shantytown.sd import SdTracker,StoreProof

def port():
 s=socket.socket();s.bind(('127.0.0.1',0));p=s.getsockname()[1];s.close();return p
with tempfile.TemporaryDirectory(prefix='dnw-private-') as tmp:
 upstream='http://127.0.0.1:'+str(port()); proxyport=port(); url='http://127.0.0.1:'+str(proxyport)
 log=open(Path(tmp)/'server.log','w')
 child=subprocess.Popen([os.environ.get('QUIPU_SERVER_BIN') or shutil.which('quipu-server'),'--db',tmp+'/q.db','--bind',upstream.removeprefix('http://')],cwd=tmp,env=dict(os.environ,HOME=tmp),stdout=log,stderr=log)
 queries=[]
 class Proxy(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_GET(self):self.forward()
  def do_POST(self):self.forward()
  def forward(self):
   body=self.rfile.read(int(self.headers.get('Content-Length','0')))
   if self.path=='/query':queries.append(json.loads(body).get('query',''))
   headers={k:v for k,v in self.headers.items() if k.lower() in ('content-type','accept','x-quipu-client')}
   try:
    with urlopen(Request(upstream+self.path,data=body if self.command=='POST' else None,headers=headers,method=self.command),timeout=10) as r:
     out=r.read();self.send_response(r.status);self.end_headers();self.wfile.write(out)
   except Exception:
    self.send_response(502);self.end_headers()
 proxy=ThreadingHTTPServer(('127.0.0.1',proxyport),Proxy);thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
 try:
  for _ in range(100):
   try:urlopen(upstream+'/health',timeout=.2).close();break
   except OSError:time.sleep(.1)
  G='https://example.test/project/dnw';N='https://seeds.local/';S='https://schema.org/'
  triples=[]
  for ident,title,status in [('a','inbox: current','open'),('b','mail: legacy','open'),('c','actual work','in_progress'),('d','inbox: receipt','closed')]:
   sub='<'+N+'item/test-'+ident+'>'
   triples.append(sub+' a <'+S+'Action> .')
   for p,v in [(S+'identifier','test-'+ident),(S+'name',title),(S+'agent','worker'),(N+'ontology/status',status),(N+'ontology/priority',1),(S+'dateCreated','2026-01-01T00:00:00Z')]:
    triples.append(sub+' <'+p+'> '+json.dumps(v)+' .')
  update='INSERT DATA { GRAPH <'+G+'> { '+' '.join(triples)+' } }'
  urlopen(Request(upstream+'/update',data=urlencode({'update':update}).encode(),headers={'Content-Type':'application/x-www-form-urlencoded','X-Quipu-Client':'seeds'}),timeout=10).close()
  result={}
  for native in (False,True):
   queries.clear(); t=SdTracker(quipu=url,prefix='test');t.prove_store=lambda:StoreProof('--quipu',None,url,'test',G)
   if not native:
    t._use_remote_projection=lambda:False
    t._bd=lambda *a:subprocess.run([os.environ.get('SD_BIN') or shutil.which('sd'),'--quipu',url,'--graph',G,*a],capture_output=True,text=True,timeout=20,cwd=tmp,env=dict(os.environ,HOME=tmp))
   rows=t.inbox_items('worker').exact()
   result['native' if native else 'sdk']={'queries':len(queries),'ids':sorted(r.id for r in rows),'shapes':[q.split()[0] for q in queries]}
  assert result['sdk']['ids']==result['native']['ids']==['test-a','test-b']
  result['ratio']=result['native']['queries']/result['sdk']['queries']
  print(json.dumps(result,indent=2))
 finally:
  proxy.shutdown();proxy.server_close();thread.join();child.terminate();child.wait(timeout=10);log.close()
