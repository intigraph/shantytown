"""Synthetic-only Unix DAC proof; no production user/key/config is touched."""
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class SessionIsolation(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid()==0,
                         'actual two-UID control requires isolated Linux CI root; no sudo on crew host')
    def test_own_key_read_other_uid_denied_and_shared_uid_is_not_isolation(self):
        with tempfile.TemporaryDirectory(prefix='crew-identity-fixture-') as d:
            base=Path(d);base.chmod(0o755)
            owner,other=51001,51002
            homes=[]
            for uid in (owner,other):
                home=base/str(uid);home.mkdir(mode=0o700);os.chown(home,uid,uid)
                key=home/'synthetic-session-key'
                subprocess.run([shutil.which('openssl') or '/usr/bin/openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(key)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                os.chown(key,uid,uid);key.chmod(0o600);homes.append(key)
            def read(uid,path):
                return subprocess.run([sys.executable,'-c','import pathlib,sys;pathlib.Path(sys.argv[1]).read_bytes()',str(path)],
                    user=uid,group=uid,extra_groups=[],env={'PATH':'/usr/bin:/bin'},
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE).returncode
            self.assertEqual(read(owner,homes[0]),0)
            self.assertEqual(read(other,homes[1]),0)
            self.assertNotEqual(read(other,homes[0]),0)
            self.assertNotEqual(read(owner,homes[1]),0)
            message=base/'request';message.write_bytes(b'synthetic-request-only')
            def sign(uid,path):
                return subprocess.run([shutil.which('openssl') or '/usr/bin/openssl', 'pkeyutl',
                    '-sign','-rawin','-inkey',str(path),'-in',str(message)],
                    user=uid,group=uid,extra_groups=[],env={'PATH':'/usr/bin:/bin'},
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE).returncode
            self.assertEqual(sign(owner,homes[0]),0)
            self.assertEqual(sign(other,homes[1]),0)
            self.assertNotEqual(sign(other,homes[0]),0)
            self.assertNotEqual(sign(owner,homes[1]),0)
            # Paired falsifier: 0600 does NOT stop another process of the SAME UID.
            self.assertEqual(read(owner,homes[0]),0)

if __name__=='__main__':unittest.main()
