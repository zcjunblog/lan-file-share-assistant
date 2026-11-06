"""Opt-in M3 capacity proof: synthetic sparse sources, full streamed private snapshots.
Run with an isolated Python3.9 environment populated only from Skill requirements.
Public output is a whitelist; no URLs, addresses, owner IDs or PIDs are published.
"""
import argparse
import hashlib
import http.client
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/m3/capacity-39'
GIB=1024**3
SIZES=[('A-2GiB.bin',2*GIB),('B-2GiB.bin',2*GIB),('C-1GiB.bin',GIB)]


def modules():
    scripts=OUT/'extracted/lan-file-share-assistant/scripts'
    sys.path.insert(0,str(scripts))
    import core,preflight,session
    assert Path(session.__file__).resolve()==scripts/'session.py'
    return core,preflight,session


def prepare():
    os.umask(0o077)
    assert sys.version_info[:2]==(3,9),'Use the isolated Python3.9 interpreter'
    assert shutil.disk_usage(str(ROOT)).free>=20*GIB,'Need at least20GiB free for this bounded test'
    assert not OUT.exists(),'Use a new output directory; preserve prior evidence'
    OUT.mkdir(mode=0o700)
    source=ROOT/'skills/lan-file-share-assistant'
    with zipfile.ZipFile(OUT/'development.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                archive.write(path,path.relative_to(source.parent))
    with zipfile.ZipFile(OUT/'development.zip') as archive:
        archive.extractall(OUT/'extracted')
    for path in (OUT/'extracted/lan-file-share-assistant').rglob('*'):
        if path.is_file():os.chmod(path,0o600)
        elif path.is_dir():os.chmod(path,0o700)
    files=OUT/'synthetic-files';files.mkdir(mode=0o700)
    for name,size in SIZES:
        with open(files/name,'xb') as stream:stream.truncate(size)
    core,preflight,_=modules()
    distributions={d.metadata['Name'].lower():d.version for d in importlib.metadata.distributions()}
    development={'jsonschema','pillow','zxing-cpp','pyyaml'}
    assert not development.intersection(distributions),'No dev-only dependencies admitted'
    core.save(OUT/'environment.json',{'python':sys.version.split()[0],'distributions':distributions,
                                    'segno_requires':importlib.metadata.distribution('segno').requires,
                                    'source_identity':{name:core.identity((files/name).stat()) for name,_ in SIZES}})
    core.save(OUT/'probe.json',preflight.start_probe(OUT/'runtime'))
    print(json.dumps({'isolated_python':sys.version.split()[0],'segno':distributions['segno'],
                      'dev_dependencies_absent':True,'source_total_bytes':sum(s for _,s in SIZES),
                      'no_file_service_yet':True}),flush=True)


def exercise():
    os.umask(0o077)
    core,_,session=modules()
    environment=core.load(OUT/'environment.json')
    assert sys.version.split()[0]==environment['python']
    files=[str(OUT/'synthetic-files'/name) for name,_ in SIZES]
    host={'kind':'local','evidence':'desktop_adapter'}
    request=dict(schema_version='1.0',title='M3合成容量上限验收',file_paths=files,
                 ttl_seconds=180,bind_address=None,port=0,host_context=host,transport='http')
    worker=[None];samples=[];done=threading.Event()
    original=session.launch
    def sample():
        while not done.wait(.2):
            if worker[0] is None or worker[0].poll() is not None:continue
            result=subprocess.run(['/bin/ps','-p',str(worker[0].pid),'-o','rss='],capture_output=True,text=True,timeout=1)
            if result.returncode==0 and result.stdout.strip().isdigit():samples.append(int(result.stdout.strip()))
    sampler=threading.Thread(target=sample,daemon=True);sampler.start()
    def launch(*args):
        worker[0]=original(*args);return worker[0]
    active=None;state=None;began=time.monotonic()
    try:
        with patch('session.launch',side_effect=launch):
            active=session.start(request,OUT/'runtime',files,host,core.load(OUT/'probe.json')['probe_id'])
        until=time.monotonic()+150
        while active['state'] not in session.TERMINAL and not active.get('can_publish') and time.monotonic()<until:
            time.sleep(.2);active=session.status(OUT/'runtime',active['session_id'])
        assert active.get('can_publish'),active
        prepared=time.monotonic()-began
        directory=session.directory_for(OUT/'runtime',active['session_id'])
        state=core.load(directory/'state.json')
        assert len(state['files'])==3 and sum(f['size_bytes'] for f in state['files'])==5*GIB
        secret=core.load(directory/'secrets.json')
        assert session.verified_health(state,secret['access_token'],verify_files=True)
        print(json.dumps({'current_python':sys.version.split()[0],'private_snapshots_ready':True,
                          'full_snapshot_bytes':5*GIB,'preparation_seconds':round(prepared,3)}),flush=True)
        expected={};zeros=b'\0'*(1024*1024)
        for size in {size for _,size in SIZES}:
            h=hashlib.sha256()
            for _ in range(size//len(zeros)):h.update(zeros)
            expected[size]=h.hexdigest()
        received=0;results=[];download_began=time.monotonic()
        for item in state['files']:
            connection=http.client.HTTPConnection(state['bind_address'],state['port'],timeout=5)
            h=hashlib.sha256();size=0
            try:
                connection.request('GET','/s/'+secret['access_token']+'/files/'+item['file_id'])
                response=connection.getresponse()
                assert response.status==200 and int(response.getheader('Content-Length'))==item['size_bytes']
                while True:
                    data=response.read(1024*1024)
                    if not data:break
                    size+=len(data);h.update(data)
                assert size==item['size_bytes'] and h.hexdigest()==expected[size]==item['sha256']
            finally:connection.close()
            received+=size;results.append({'size_bytes':size,'sha256_matches_independent_zero_fixture':True})
            print(json.dumps({'files_received':len(results),'bytes_verified':received}),flush=True)
        download_seconds=time.monotonic()-download_began
        assert received==5*GIB
        assert all(core.identity((OUT/'synthetic-files'/name).stat())==environment['source_identity'][name] for name,_ in SIZES)
        stopped=session.stop(OUT/'runtime',active['session_id'])
        assert stopped['state']=='stopped' and stopped['temporary_resources_removed']
        worker[0].wait(timeout=3)
        try:connection=socket.create_connection((state['bind_address'],state['port']),timeout=.3)
        except OSError:pass
        else:connection.close();raise AssertionError('Listener remained open')
        assert samples and max(samples)<256*1024,'Observed server RSS unexpectedly exceeds256MiB'
        # These sources were created solely by this test, and checked unchanged first.
        for name,_ in SIZES:(OUT/'synthetic-files'/name).unlink()
        source=ROOT/'skills/lan-file-share-assistant';extracted=OUT/'extracted/lan-file-share-assistant'
        archive_files=[p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
        assert all((extracted/p.relative_to(source)).read_bytes()==p.read_bytes() for p in archive_files)
        summary={'python':environment['python'],'platform':'macOS','source_revision':'e618681',
                 'direct_runtime_requirement':'segno==1.6.6','installed_distributions':environment['distributions'],
                 'development_dependencies_absent':True,'extracted_skill_matches_source':True,
                 'production_preflight_passed':True,'independent_status_health_passed':True,
                 'source_count':3,'single_file_max_bytes':2*GIB,'aggregate_bytes':received,'files':results,
                 'preparation_seconds':round(prepared,3),'self_http_stream_seconds':round(download_seconds,3),
                 'observed_server_rss_peak_mib':round(max(samples)/1024,1),'rss_samples':len(samples),
                 'source_identity_unchanged_before_test_cleanup':True,'synthetic_sources_cleaned_after_check':True,
                 'manual_stop_verified':True,'listener_closed':True,'private_snapshots_and_credentials_removed':True,
                 'receiver':'same_machine_http_client','cross_device_large_file_tested':False,
                 'realistic_throughput_benchmark':False,'real_system_sleep_tested':False}
        core.save(ROOT/'evidence/m3/runtime-39-capacity.json',summary)
        print(json.dumps({'python39_capacity_acceptance_passed':True,'bytes_verified':received,
                          'observed_server_rss_peak_mib':summary['observed_server_rss_peak_mib'],'test_resources_cleaned':True}),flush=True)
    finally:
        done.set();sampler.join(timeout=2)
        if active and active.get('session_id'):
            result=session.status(OUT/'runtime',active['session_id'])
            if result['state'] not in session.TERMINAL:
                result=session.stop(OUT/'runtime',active['session_id'])
                if worker[0] and worker[0].poll() is None:
                    worker[0].terminate();worker[0].wait(timeout=3)
                    session.clean(session.directory_for(OUT/'runtime',active['session_id']))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','exercise'])
    args=parser.parse_args();{'prepare':prepare,'exercise':exercise}[args.command]()
