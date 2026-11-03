"""Execute generated transaction scripts in a temporary fake robot filesystem.
sudo/systemctl/ldd/scp are fixtures; no SSH, system service or real robot is used.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from operations_fixture import Fixture


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.robot=self.f.root/'fake-robot';self.robot.mkdir()
        (self.robot/'maximus_main').write_bytes(b'previous working robot binary')
        (self.robot/'config').mkdir();(self.robot/'config/old-only.yaml').write_text('previous: true\n')
        (self.robot/'config/version.txt').write_text('old-version\n')
        (self.robot/'config/deploy.yaml').write_text('robot: t1\nnumber: 6\n')
        (self.robot/'state').write_text('active')
        (self.robot/'old-hash').write_text(hashlib.sha256((self.robot/'maximus_main').read_bytes()).hexdigest())
        commands=self.f.root/'commands';commands.mkdir()
        (commands/'sudo').write_text('#!/bin/sh\n[ "$1" = -n ] && shift\n[ "$1" = -v ] && exit 0\nexec "$@"\n')
        (commands/'ldd').write_text('#!/bin/sh\necho "fixture dependencies resolved"\n')
        (commands/'systemctl').write_text('''#!/usr/bin/env python3
import os,sys,hashlib
from pathlib import Path
r=Path(os.environ['FAKE_ROBOT']);args=sys.argv[1:];verb=args[0]
if verb=='show': print('ExecStart='+str(r/'maximus_main'))
elif verb=='is-active':
    state=(r/'state').read_text()
    if '--quiet' not in args:print(state)
    sys.exit(0 if state=='active' else 3)
elif verb=='stop':(r/'state').write_text('inactive')
elif verb=='start':
    if (r/'fail-old').exists() and hashlib.sha256((r/'maximus_main').read_bytes()).hexdigest()==(r/'old-hash').read_text():sys.exit(1)
    if (r/'fail-new').exists() and hashlib.sha256((r/'maximus_main').read_bytes()).hexdigest()!=(r/'old-hash').read_text():sys.exit(1)
    (r/'state').write_text('active')
else:sys.exit(2)
''')
        for path in commands.iterdir():path.chmod(0o700)
        self.env={**os.environ,'PATH':str(commands)+':'+os.environ['PATH'],'FAKE_ROBOT':str(self.robot)}
        self.f.jobs.runner=self.transport

    def tearDown(self):self.f.close()

    def transport(self,identifier,argv,**kwargs):
        if argv[0]=='scp':
            remote=argv[-1].split(':',1)[1].replace('/home/test/robot',str(self.robot))
            shutil.copyfile(argv[-2],remote)
            return ''
        self.assertEqual(argv[0],'ssh')
        script=kwargs['input'].replace('/home/test/robot',str(self.robot))
        result=subprocess.run(['bash','-se'],input=script,text=True,capture_output=True,env=self.env,timeout=15)
        if result.returncode:raise ValueError(result.stdout+result.stderr)
        return result.stdout

    def test_success_then_exact_rollback(self):
        deployed=self.f.wait(self.f.submit('deploy',artifact=self.f.artifact))
        self.assertEqual(deployed['status'],'succeeded',deployed)
        self.assertFalse((self.robot/'config/old-only.yaml').exists())
        self.assertTrue((self.robot/'config/deploy.yaml').is_file())
        rolled=self.f.wait(self.f.submit('rollback',job=deployed['id']))
        self.assertEqual(rolled['status'],'succeeded',rolled)
        self.assertEqual((self.robot/'maximus_main').read_bytes(),b'previous working robot binary')
        self.assertTrue((self.robot/'config/old-only.yaml').is_file())
        self.assertEqual((self.robot/'config/deploy.yaml').read_text(),'robot: t1\nnumber: 6\n')
        self.assertEqual((self.robot/'config/version.txt').read_text(),'old-version\n')
        self.assertEqual((self.robot/'state').read_text(),'active')

    def test_failed_activation_restores_binary_config_and_service(self):
        (self.robot/'fail-new').touch()
        result=self.f.wait(self.f.submit('deploy',artifact=self.f.artifact))
        self.assertEqual(result['status'],'failed',result)
        self.assertIn('ACTIVATION_FAILED_RESTORED',result['error'])
        self.assertEqual((self.robot/'maximus_main').read_bytes(),b'previous working robot binary')
        self.assertEqual((self.robot/'config/version.txt').read_text(),'old-version\n')
        self.assertEqual((self.robot/'config/deploy.yaml').read_text(),'robot: t1\nnumber: 6\n')
        self.assertEqual((self.robot/'state').read_text(),'active')

    def test_failed_rollback_restores_current_installation(self):
        deployed=self.f.wait(self.f.submit('deploy',artifact=self.f.artifact))
        self.assertEqual(deployed['status'],'succeeded',deployed)
        current=(self.robot/'maximus_main').read_bytes()
        version=(self.robot/'config/version.txt').read_bytes()
        (self.robot/'fail-old').touch()
        rolled=self.f.wait(self.f.submit('rollback',job=deployed['id']))
        self.assertEqual(rolled['status'],'failed',rolled)
        self.assertIn('ROLLBACK_FAILED_RESTORED',rolled['error'])
        self.assertEqual((self.robot/'maximus_main').read_bytes(),current)
        self.assertEqual((self.robot/'config/version.txt').read_bytes(),version)
        self.assertEqual((self.robot/'state').read_text(),'active')

    def test_service_failure_is_not_hidden_by_status_query(self):
        (self.robot/'fail-old').touch()
        result=self.f.wait(self.f.submit('service-start'))
        self.assertEqual(result['status'],'failed',result)


if __name__=='__main__':unittest.main()
