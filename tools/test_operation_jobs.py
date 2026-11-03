import json
from pathlib import Path
import threading
import time
import unittest

from operations_fixture import Fixture, OPERATORS, TOKEN
from operation_jobs import OperationJobs
from simulation_jobs import normalize


SCENARIO = {"name":"fixture", "field":{"width":14,"height":9}, "ball":{"x":0,"y":0}, "teams":[
    {"number":19,"players":[{"number":6,"source":"real","model":"t1","role":"striker","x":-2,"y":0,"angle":0}]},
    {"number":2,"players":[{"number":1,"source":"ghost","model":"k1","role":"goalie","x":2,"y":0,"angle":0}]}]}


class JobsTest(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def tearDown(self): self.f.close()

    def test_authorization_preview_support_and_expiry(self):
        jobs=self.f.jobs
        self.assertEqual(jobs.identity(TOKEN),'tester')
        for token in ('', 'wrong'):
            with self.assertRaises(PermissionError): jobs.identity(token)
        with self.assertRaises(PermissionError): jobs.preview('reader',{'action':'service-restart','target':'robot6'})
        with self.assertRaises(PermissionError): jobs.preview('tester',{'action':'service-restart','target':'elsewhere'})
        with self.assertRaises(PermissionError): jobs.preview('tester',{'action':'shell','target':'robot6'})
        preview=jobs.preview('tester',{'action':'service-restart','target':'robot6'})
        self.assertEqual(self.f.calls,[],'preview never executes commands')
        request={'preview':preview['preview'],'key':'request-0001','confirm':'robot6'}
        with self.assertRaisesRegex(ValueError,'supported'):jobs.submit('tester',request)
        jobs.previews[preview['preview']]['expires']=0
        with self.assertRaisesRegex(ValueError,'expired'):jobs.submit('tester',{**request,'supported':True})

    def test_idempotency_and_persistent_audit(self):
        jobs=self.f.jobs
        preview=jobs.preview('tester',{'action':'service-start','target':'robot6'})
        request={'preview':preview['preview'],'key':'request-0001','confirm':'robot6','supported':True}
        first=jobs.submit('tester',request)
        self.assertEqual(jobs.submit('tester',request)['id'],first['id'])
        result=self.f.wait(first);self.assertEqual(result['status'],'succeeded')
        self.assertEqual(len(self.f.calls),2)
        restarted=OperationJobs(self.f.inspector,self.f.root/'artifacts',self.f.config,runner=self.f.run,operators=OPERATORS)
        self.assertEqual(restarted.submit('tester',request)['id'],first['id'])
        with self.assertRaises(ValueError):restarted.get('reader',first['id'])
        self.assertNotIn(TOKEN,(jobs.root/(first['id']+'.json')).read_text())

    def test_new_layout_staging_and_secret_exclusion(self):
        result=self.f.wait(self.f.submit('stage',profile='practice'))
        self.assertEqual(result['status'],'succeeded',result)
        artifact=self.f.root/'artifacts'/result['result']['id']
        text=(artifact/'config/deploy.yaml').read_text()
        self.assertIn('scenario: real',text);self.assertNotIn('psk',text)
        self.assertFalse((artifact/'config/settings.yaml').exists())

    def test_deploy_transaction_and_rollback_are_bounded(self):
        result=self.f.wait(self.f.submit('deploy',artifact=self.f.artifact))
        self.assertEqual(result['status'],'succeeded',result)
        scripts=[kw.get('input','') for _,kw in self.f.calls]
        self.assertTrue(any('ldd -r' in s and 'sha256sum -c' in s for s in scripts))
        activation=next(s for s in scripts if 'ACTIVATION_VERIFIED' in s)
        self.assertIn('trap restore EXIT HUP INT TERM',activation)
        self.assertLess(activation.index('cp -a /home/test/robot/maximus_main'),activation.index('systemctl stop'))
        self.assertNotIn('nmcli',activation)
        rolled=self.f.wait(self.f.submit('rollback',job=result['id']))
        self.assertEqual(rolled['status'],'succeeded',rolled)

    def test_failure_is_not_success(self):
        self.f.fail=True
        result=self.f.wait(self.f.submit('service-restart'))
        self.assertEqual(result['status'],'failed')
        self.assertIn('transport failure',result['error'])
        self.assertIsNone(self.f.jobs.active)

    def test_network_recovery_precedes_apply_and_uses_second_probe(self):
        result=self.f.wait(self.f.submit('network-apply',profile='wifi'))
        self.assertEqual(result['status'],'succeeded',result)
        script=self.f.calls[0][1]['input']
        self.assertLess(script.index('--on-active=90s'),script.index('nmcli --wait 30 connection up'))
        self.assertIn('RECOVERY_TIMER_CANCELLED',self.f.calls[1][1]['input'])
        self.assertEqual(self.f.wait(self.f.submit('network-rollback',job=result['id']))['status'],'succeeded')

    def test_simulation_isolation_and_cancel_cleanup(self):
        result=self.f.submit('simulate',scenario=SCENARIO)
        for _ in range(100):
            if self.f.jobs.get('tester',result['id'])['phase']=='simulator running':break
            time.sleep(.02)
        argv=self.f.calls[0][0]
        self.assertEqual(argv[argv.index('--network')+1],'none')
        directory=self.f.jobs.root/(result['id']+'-scenario')
        scene=(directory/'scene.yaml').read_text()
        self.assertNotIn('number: 6',scene);self.assertIn('Booster-K1',scene)
        with self.assertRaisesRegex(ValueError,'Another operation'):self.f.submit('service-start')
        self.f.jobs.cancel('tester',result['id'])
        self.assertEqual(self.f.wait(result)['status'],'cancelled')
        self.assertEqual(self.f.calls[-1][0][:3],['docker','rm','-f'])

    def test_gateway_network_requires_browser_confirmation(self):
        job=self.f.submit('network-apply',target='gateway',profile='sharing')
        for _ in range(100):
            if self.f.jobs.get('tester',job['id'])['phase']=='awaiting network confirmation':break
            time.sleep(.02)
        self.assertEqual(len(self.f.calls),1,'recovery must remain armed until confirmed')
        with self.assertRaises(ValueError):self.f.jobs.confirm_network('reader',job['id'])
        self.f.jobs.confirm_network('tester',job['id'])
        self.assertEqual(self.f.wait(job)['status'],'succeeded')
        self.assertIn('RECOVERY_TIMER_CANCELLED',self.f.calls[1][1]['input'])

    def test_cancelled_gateway_network_keeps_recovery_armed(self):
        job=self.f.submit('network-apply',target='gateway',profile='sharing')
        for _ in range(100):
            if self.f.jobs.get('tester',job['id'])['phase']=='awaiting network confirmation':break
            time.sleep(.02)
        self.f.jobs.cancel('tester',job['id'])
        result=self.f.wait(job)
        self.assertIn('recovery timer remains armed',result['error'])
        self.assertEqual(len(self.f.calls),1)

    def test_invalid_scenarios(self):
        bad=json.loads(json.dumps(SCENARIO));bad['ball']['x']=1
        with self.assertRaisesRegex(ValueError,'centre'):normalize(bad)
        bad=json.loads(json.dumps(SCENARIO));bad['teams'][1]['players'][0]['x']=float('nan')
        with self.assertRaisesRegex(ValueError,'pose'):normalize(bad)


if __name__=='__main__':unittest.main()
