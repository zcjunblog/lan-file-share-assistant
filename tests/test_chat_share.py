"""The first chat call never exposes a share before an independent status check."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/lan-file-share-assistant/scripts'))
import preflight
import session


class ChatShareTests(unittest.TestCase):
    def test_chat_start_returns_only_pending_session_and_runs_managed_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / 'synthetic.txt'
            source.write_text('synthetic', encoding='utf-8')
            context = {'kind': 'local', 'evidence': 'desktop_adapter'}
            req = dict(schema_version='1.0', title='synthetic', file_paths=[str(source)],
                       ttl_seconds=600, bind_address='192.168.0.10', port=0,
                       host_context=context, transport='http')
            with patch('session.run', return_value=(req, {'can_start': True}, [])) as admit, \
                    patch('session.launch') as launch, patch('session.status') as status:
                result = session.start(req, base / 'runtime', req['file_paths'], context, None, chat=True)
            self.assertTrue(admit.call_args.kwargs['inline_probe'])
            launch.assert_called_once()
            status.assert_not_called()
            self.assertEqual(result['state'], 'preparing')
            self.assertFalse(result['can_publish'])
            self.assertTrue(result['session_id'])
            for key in ('url', 'qr_png', 'qr_svg'):
                self.assertNotIn(key, result)

    def test_inline_probe_is_not_started_after_a_blocked_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'runtime'
            context = {'kind': 'unknown', 'evidence': 'none'}
            req = dict(schema_version='1.0', title='synthetic', file_paths=[], folder_mode=True,
                       ttl_seconds=600, bind_address=None, port=0, host_context=context, transport='http')
            with patch('preflight.start_probe') as launch, patch('preflight.interfaces', return_value=[]):
                _, report, _ = preflight.run(req, root, [], context, inline_probe=True)
            launch.assert_not_called()
            self.assertFalse(report['can_start'])
            self.assertFalse(report['can_publish'])
            self.assertEqual(report['checks'][0]['reason_code'], 'host_unconfirmed')
