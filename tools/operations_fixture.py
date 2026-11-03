"""No-robot Operations fixture: every subprocess and remote action is recorded/faked."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace as N
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from operations import OperationsInspector
from operation_jobs import OperationJobs
from artifact_stage import stage

TOKEN = 'offline-operator-token-123456789'
OPERATORS = {'tester': {'token': TOKEN, 'roles': ['software','deploy','service','network','simulation'], 'targets':['robot6','gateway']},
             'reader': {'token':'offline-reader-token-123456789', 'roles':[], 'targets':[]}}

class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='oraculum-jobs-')
        self.root = Path(self.tmp.name)
        self.repo = self.root/'repo';self.repo.mkdir()
        binary = self.repo/'build/aarch64-t1/src/app/maximus_main';binary.parent.mkdir(parents=True)
        header = bytearray(24);header[:4]=b'\x7fELF';header[5]=1;header[18:20]=(183).to_bytes(2,'little');binary.write_bytes(header)
        cfg = self.repo/'src/app/config';cfg.mkdir(parents=True)
        (cfg/'deploy.yaml').write_text('robot: t1\nscenario: sim_fast\nwifi:\n  psk: fixture-secret-excluded\n')
        subprocess.run(['git','init','-q',str(self.repo)],check=True)
        subprocess.run(['git','-C',str(self.repo),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.repo),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],check=True)
        self.target={'id':'robot6','name':'Fixture robot','ip':'192.0.2.6','subnet':'192.0.2.0/24','user':'booster','service':'maximus','model':'t1','number':6,'dual_board':False,'repo':str(self.repo),'oraculum_host':'192.0.2.1','gateway_address':'192.0.2.1','gateway_connected':True}
        self.inspector=N(targets={'robot6':self.target},inventory=lambda:{'targets':[self.target],'interfaces':[]})
        self.config={'operations':{'build_argv':['fixture-build'],'deployments':{'robot6':{'binary':'/home/test/robot/maximus_main','config':'/home/test/robot/config'}},
          'network_profiles':[{'id':'wifi','label':'Lab Wi-Fi','target':'robot6','uuid':'12345678-1234-1234-1234-123456789abc','interface':'wlan0'},
                              {'id':'sharing','label':'Laptop internet sharing','target':'gateway','uuid':'abcdefab-1234-1234-1234-123456789abc','interface':'wlan0'}],
          'simulator':{'image':'fixture/simulator@sha256:'+'a'*64,'max_seconds':30}}}
        self.calls=[];self.fail=False;self.sim_running=True
        self.jobs=OperationJobs(self.inspector,self.root/'artifacts',self.config,runner=self.run,operators=OPERATORS)
        self.artifact=stage(self.repo,self.target,'practice',self.root/'artifacts')['id']

    def run(self, identifier, argv, **kwargs):
        self.calls.append((list(argv),kwargs))
        time.sleep(.02)
        if self.fail: raise ValueError('fixture transport failure')
        if argv[:2]==['docker','inspect']:return json.dumps({'Running':self.sim_running,'ExitCode':0,'Error':''})
        return 'ActiveState=active\nResult=success\n' if argv[0]=='ssh' else 'fixture process completed'

    def submit(self, action, **kwargs):
        preview=self.jobs.preview('tester',{'action':action,'target':None if action=='simulate' else 'robot6',**kwargs})
        return self.jobs.submit('tester',{'preview':preview['preview'],'key':os.urandom(8).hex(),'confirm':preview['confirmation'],'supported':True})

    def wait(self, job):
        for _ in range(400):
            result=self.jobs.get('tester',job['id'])
            if result['status'] not in ('queued','running'):return result
            time.sleep(.03)
        raise AssertionError('fixture job did not finish')

    def close(self):
        for event in self.jobs.cancelled.values():event.set()
        for _ in range(400):
            if not self.jobs.active:break
            time.sleep(.03)
        self.tmp.cleanup()

    def start_server(self):
        import control_server as cs
        # Suppress every receiver/background sender. The browser reaches only this loopback HTTP fixture.
        previous=os.environ.get('ORACULUM_ACCESS_TOKEN')
        os.environ['ORACULUM_ACCESS_TOKEN']='offline-gateway-token'
        try:self.server=cs.ControlServer()
        finally:
            if previous is None:os.environ.pop('ORACULUM_ACCESS_TOKEN',None)
            else:os.environ['ORACULUM_ACCESS_TOKEN']=previous
        s=self.server;s.match=False;s.operations=self.inspector;s.operation_jobs=self.jobs;s.artifact_root=str(self.root/'artifacts')
        for part in (s.udp_receiver,s.gc_receiver,s.events,s.reception,s.camera_hub):part.start=lambda:None
        s.udp_receiver.latest=lambda:N(agents=[],to_dict=lambda:{'agents':[],'ball':None,'drawings':[],'texts':[]})
        s.udp_receiver.link_stats=lambda:{};s.gc_receiver.latest=lambda:None;s.git_head=lambda:''
        s.events.add=lambda *a,**k:None
        def forbidden(*a,**k):raise AssertionError('fixture attempted robot traffic')
        s.send_joystick=forbidden;s.camera_hub.request=forbidden
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));s.http_port=probe.getsockname()[1]
        s.start()
        return f'http://127.0.0.1:{s.http_port}'
