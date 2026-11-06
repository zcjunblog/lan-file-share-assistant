"""Opt-in synthetic M3 lifecycle acceptance. Signals only Popen objects created here."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/lan-file-share-assistant/scripts'))
import core
import preflight
import session
OUT=ROOT/'outputs/m3/lifecycle'


def prepare():
    os.umask(0o077)
    OUT.mkdir(mode=0o700,parents=True,exist_ok=True)
    source=OUT/'synthetic.txt'
    source.write_text('M3 isolated lifecycle fixture.\n'*1000)
    core.save(OUT/'probe.json',preflight.start_probe(OUT/'runtime'))
    print('Bounded no-network probe started; run exercise in the next tool call.')


def request(active,suffix=''):
    url=urlsplit(active['url'])
    connection=http.client.HTTPConnection(url.hostname,url.port,timeout=1)
    try:
        connection.request('GET',url.path+suffix)
        response=connection.getresponse()
        return response.status,response.read()
    finally:connection.close()


def closed(state):
    try:connection=socket.create_connection((state['bind_address'],state['port']),timeout=.3)
    except OSError:return True
    connection.close();return False


def exercise():
    os.umask(0o077)
    root=OUT/'runtime';source=OUT/'synthetic.txt';before=hashlib.sha256(source.read_bytes()).hexdigest()
    proof=core.load(OUT/'probe.json')['probe_id']
    host={'kind':'local','evidence':'desktop_adapter'}
    req=dict(schema_version='1.0',title='M3合成生命周期验收',file_paths=[str(source)],ttl_seconds=60,
             bind_address=None,port=0,host_context=host,transport='http')
    launches=[];owned=[]
    original=session.launch
    def launch(*args):
        process=original(*args);launches.append(process);return process
    def create():
        with patch('session.launch',side_effect=launch):
            active=session.start(req,root,[str(source)],host,proof)
        assert active['state']=='ready' and active['can_publish']
        state=core.load(session.directory_for(root,active['session_id'])/'state.json')
        secret=core.load(session.directory_for(root,active['session_id'])/'secrets.json')
        assert session.verified_health(state,secret['access_token'])
        item=(launches[-1],active,state);owned.append(item);return item
    summary={}
    try:
        a=create();b=create();c=create()
        assert len({i[1]['url'] for i in (a,b,c)})==3
        # Cross-session file IDs and access tokens are never interchangeable.
        assert request(a[1],'files/'+b[2]['files'][0]['file_id'])[0]==404
        for _ in range(2):assert request(c[1])[0]==200
        state_path=session.directory_for(root,c[1]['session_id'])/'state.json'
        assert core.load(state_path)['expires_at']==c[2]['expires_at']
        result=session.stop(root,c[1]['session_id']);assert result['state']=='stopped'
        assert closed(c[2]) and session.status(root,a[1]['session_id'])['can_publish']
        assert session.stop(root,c[1]['session_id'])['state']=='stopped'
        c[0].wait(timeout=2)
        summary.update(repeated_sessions_independent=True,repeated_get_does_not_extend_ttl=True,
                       cross_session_file_rejected=True,stopping_one_preserves_other=True,repeated_stop_idempotent=True)
        # Kill only this harness's known live Popen child after authenticated ownership.
        assert b[0].poll() is None
        b[0].kill();b[0].wait(timeout=2)
        result=session.status(root,b[1]['session_id'])
        assert result['state']=='unverified_stale' and not result['can_publish'] and 'url' not in result
        assert closed(b[2])
        directory=session.directory_for(root,b[1]['session_id'])
        assert (directory/'secrets.json').exists() and (directory/'snapshots').exists()
        # Explicit test cleanup is safe only because this exact owned child was waited.
        session.clean(directory)
        state=core.load(directory/'state.json');state.update(state='failed',last_error='test_forced_exit')
        core.save(directory/'state.json',state)
        summary.update(owned_sigkill_listener_closed=True,forced_exit_never_reports_ready=True,
                       forced_exit_leaves_private_resources=True,owned_test_resources_manually_cleaned=True)
        assert a[0].poll() is None
        a[0].send_signal(signal.SIGSTOP)
        print(json.dumps({'parallel_session_isolation_passed':True,'forced_exit_fail_closed':True,
                          'waiting_for_owned_process_resume_after_real_deadline':True}),flush=True)
        deadline=__import__('datetime').datetime.fromisoformat(a[2]['expires_at'].replace('Z','+00:00')).timestamp()
        while time.time()<deadline+.2:time.sleep(.1)
        began=time.monotonic();a[0].send_signal(signal.SIGCONT)
        while time.monotonic()-began<2:
            result=session.status(root,a[1]['session_id'])
            if result['state']=='expired':break
            time.sleep(.03)
        assert result['state']=='expired' and result['temporary_resources_removed'] and closed(a[2])
        a[0].wait(timeout=2)
        summary.update(process_pause_resume_expired=True,resume_to_cleanup_seconds=round(time.monotonic()-began,3),
                       real_system_sleep_tested=False,system_clock_changed=False,source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==before)
        assert summary['source_unchanged']
        core.save(ROOT/'evidence/m3/lifecycle.json',summary)
        print(json.dumps(summary))
    finally:
        # No test-owned paused process can remain indefinitely on assertion failure.
        for process,active,state in owned:
            if process.poll() is None:
                process.send_signal(signal.SIGCONT)
                result=session.stop(root,active['session_id'])
                if result['state'] not in session.TERMINAL:
                    process.terminate()  # exact Popen child owned by this test only
                process.wait(timeout=3)
                session.clean(session.directory_for(root,active['session_id']))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','exercise'])
    args=parser.parse_args();{'prepare':prepare,'exercise':exercise}[args.command]()
