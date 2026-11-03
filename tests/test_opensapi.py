import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ou_dedetai.opensapi import ASSET, Speech
from ou_dedetai.logos import State, LogosManager
import subprocess


class SpeechTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict('os.environ', {'XDG_DATA_HOME': str(self.root / 'share')})
        environment.start()
        self.addCleanup(environment.stop)
        self.app = Mock()
        self.app.conf.wine_prefix = '/logos/prefix'
        self.app.conf.wine_binary = '/wine/AppImage'
        self.app.logos.logos_state = State.STOPPED
        self.speech = Speech(self.app)

    def test_only_shared_binary_path_is_derived(self):
        self.assertEqual(self.speech.binary, self.root / 'share/OpenSAPI' / ASSET)
        self.assertEqual(self.speech.command('--configure'), [str(self.speech.binary), '--configure'])

    def test_latest_standalone_download_and_checksum(self):
        data = b'AppImage'
        def release(date, standalone=True):
            names = (ASSET, 'SHA256SUMS') if standalone else ('Wine.AppImage',)
            return {'published_at': date, 'draft': False, 'assets': [
                {'name': name, 'browser_download_url': 'https://example/' + date + '/' + name} for name in names]}
        listing = Mock()
        listing.json.return_value = [release('2026-11-03', False), release('2026-11-01'), release('2026-11-02')]
        checksum = Mock(text=hashlib.sha256(data).hexdigest() + '  ' + ASSET + '\r\n')
        download = Mock()
        download.__enter__ = Mock(return_value=download)
        download.__exit__ = Mock(return_value=False)
        download.iter_content.return_value = [data]
        with patch('ou_dedetai.opensapi.requests.get', side_effect=[listing, checksum, download]) as get:
            self.speech.download()
        self.assertIn('/2026-11-02/', get.call_args_list[1].args[0])
        self.assertEqual(self.speech.binary.read_bytes(), data)
        self.assertTrue(self.speech.binary.stat().st_mode & 0o111)

    def test_checksum_failure_preserves_existing_binary(self):
        self.speech.binary.parent.mkdir(parents=True)
        self.speech.binary.write_bytes(b'original')
        listing = Mock()
        listing.json.return_value = [{'published_at': '', 'draft': False, 'assets': [
            {'name': name, 'browser_download_url': 'https://example/' + name} for name in (ASSET, 'SHA256SUMS')]}]
        checksum = Mock(text='0' * 64 + '  ' + ASSET)
        download = Mock()
        download.__enter__ = Mock(return_value=download)
        download.__exit__ = Mock(return_value=False)
        download.iter_content.return_value = [b'bad']
        with patch('ou_dedetai.opensapi.requests.get', side_effect=[listing, checksum, download]):
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                self.speech.download()
        self.assertEqual(self.speech.binary.read_bytes(), b'original')

    def test_start_stop_use_public_session_commands_only(self):
        self.speech.binary.parent.mkdir(parents=True)
        self.speech.binary.touch()
        with patch('ou_dedetai.opensapi.subprocess.run') as run:
            self.speech.start()
            session = self.speech.session
            self.speech.stop()
        self.assertIn('--acquire-session', run.call_args_list[0].args[0])
        self.assertIn('--owner-pid', run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0][-2:], ['--release-session', session])
        self.assertIsNone(self.speech.session)

    def test_no_session_means_no_stop_request(self):
        with patch('ou_dedetai.opensapi.subprocess.run') as run:
            self.speech.stop()
        run.assert_not_called()

    def test_install_passes_prefix_and_wine_but_no_private_settings(self):
        self.speech.binary.parent.mkdir(parents=True)
        self.speech.binary.touch()
        with patch('ou_dedetai.opensapi.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '2')) as run, \
                patch('ou_dedetai.opensapi.subprocess.Popen') as panel:
            self.speech.configure()
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('--wine-prefix') + 1], self.app.conf.wine_prefix)
        self.assertNotIn('--settings', args)
        self.assertEqual(panel.call_args.args[0][-1], '--configure')


class SpeechLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.app.conf.speech_enabled = True
        self.manager = LogosManager(self.app)
        self.manager.speech = Mock()
        self.manager.prevent_logos_updates = Mock()
        self.manager.set_auto_updates = Mock()
        self.app.start_thread.side_effect = lambda function, **kwargs: (
            function() if function.__name__ == 'run_logos' else None)

    def launch(self, result):
        with patch('ou_dedetai.logos.wine.get_wine_release', return_value=(None, None)), \
                patch('ou_dedetai.logos.wine.check_wine_rules', return_value=(True, None)), \
                patch('ou_dedetai.logos.wine.wineserver_kill'), \
                patch('ou_dedetai.logos.wine.run_wine_application', **result):
            self.manager.start()

    def test_speech_failure_still_launches_logos(self):
        self.manager.speech.start.side_effect = RuntimeError('Missing model')
        self.launch({'return_value': Mock(spec=subprocess.Popen)})
        self.assertEqual(self.manager.logos_state, State.RUNNING)
        self.app.status.assert_called_once()

    def test_disabled_speech_does_not_start_backend(self):
        self.app.conf.speech_enabled = False
        self.launch({'return_value': Mock(spec=subprocess.Popen)})
        self.manager.speech.start.assert_not_called()

    def test_failed_logos_launch_stops_owned_backend(self):
        self.launch({'return_value': None})
        self.manager.speech.stop.assert_called_once()
        self.assertEqual(self.manager.logos_state, State.STOPPED)

    def test_logos_exit_stops_backend(self):
        self.manager.logos_state = State.RUNNING
        self.manager.monitor_logos()
        self.manager.speech.stop.assert_called_once()
        self.assertEqual(self.manager.logos_state, State.STOPPED)
