"""Platform dispatch and Linux OS metadata policy, no real user files."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/lan-file-share-assistant/scripts'
sys.path.insert(0,str(SCRIPTS))
import core


class LinuxPolicy(unittest.TestCase):
    def setUp(self):
        self.backend=importlib.import_module('linux_backend')
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def interface(self,name,device=True,state='up',kind='1',flags='0x1003'):
        p=self.base/name;p.mkdir()
        for key,value in [('operstate',state),('type',kind),('flags',flags)]: (p/key).write_text(value)
        if device:(p/'device').mkdir()
    def test_only_up_hardware_rfc1918_adapters(self):
        self.interface('eth0');self.interface('wifi0');self.interface('tun0',device=False)
        self.interface('lo',device=False,kind='772');self.interface('down0',state='down')
        self.interface('public0')
        addresses={'eth0':'192.168.1.2','wifi0':'10.0.0.2','tun0':'10.9.0.2','lo':'127.0.0.1','down0':'192.168.1.3','public0':'203.0.113.8'}
        rows=self.backend.interfaces(sysfs_root=self.base,address_reader=addresses.__getitem__)
        self.assertEqual(rows,[{'interface':'eth0','address':'192.168.1.2'},{'interface':'wifi0','address':'10.0.0.2'}])
    def test_partial_metadata_or_denied_address_does_not_guess(self):
        self.interface('eth0')
        (self.base/'eth0/operstate').unlink()
        with self.assertRaises(core.ShareError):self.backend.interfaces(sysfs_root=self.base,address_reader=lambda n:'10.0.0.2')
    def test_suspend_clock_has_no_monotonic_fallback(self):
        with patch.object(self.backend.time,'CLOCK_BOOTTIME',None,create=True):
            with self.assertRaises(core.ShareError) as caught:self.backend.continuous_seconds()
        self.assertEqual(caught.exception.code,'clock_backend_unverified')
        with patch.object(self.backend.time,'CLOCK_BOOTTIME',7,create=True),patch.object(self.backend.time,'clock_gettime',return_value=12.5,create=True):
            self.assertEqual(self.backend.continuous_seconds(),12.5)


class NativeRuntime(unittest.TestCase):
    def test_runtime_and_suspend_clock_on_actual_host(self):
        core.runtime_available()
        clock=core.ContinuousClock();before=clock.now();time.sleep(.02)
        self.assertGreater(clock.now(),before)
    def test_private_reader_releases_for_atomic_state_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();root=core.workspace(base/'owned')
            p=root/'state.json';core.save(p,{'value':1})
            with core.open_private_binary(p) as stream:
                core.save(p,{'value':2})
                self.assertIn(b'1',stream.read())
            self.assertEqual(core.load(p),{'value':2})
    def test_windows_lexical_validation_routes_without_ntfs_on_posix(self):
        if os.name=='nt':self.skipTest('Pure dispatch check is POSIX-host-only')
        with patch('sys.platform','win32'):
            with self.assertRaises(core.ShareError):core.physical('C:\\data\\file.txt:secret')


if __name__=='__main__':unittest.main()
