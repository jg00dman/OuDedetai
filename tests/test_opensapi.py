import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from ou_dedetai.config import Config, LegacyConfiguration, PersistentConfiguration
from ou_dedetai.logos import LogosManager, State
from ou_dedetai.opensapi import ASSET, Speech


class SpeechTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.app = Mock()
        self.app.conf.install_dir = str(self.root)
        self.app.conf.installer_binary_dir = str(self.root / 'bin')
        self.app.conf.wine_prefix = str(self.root / 'prefix')
        self.app.conf.wine_binary = '/wine/AppImage'
        self.app.logos.logos_state = State.STOPPED
        self.speech = Speech(self.app)
        self.speech.settings.parent.mkdir(parents=True)
        self.speech.settings.write_text(json.dumps({'port': 5000, 'voices': {}}))
        self.app.logos.speech = self.speech

    def test_uses_wine_binary_directory_and_separate_installation_profile(self):
        self.assertEqual(self.speech.binary, self.root / 'bin' / ASSET)
        self.assertEqual(self.speech.settings, self.root / 'data/opensapi/settings.json')

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
        self.speech.binary.parent.mkdir()
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

    def test_reused_server_is_never_stopped(self):
        self.speech.health = Mock(return_value={'settings': str(self.speech.settings.resolve()), 'ready': True})
        with patch('ou_dedetai.opensapi.subprocess.Popen') as spawn, patch('os.killpg') as kill:
            self.speech.start()
            self.speech.stop()
        spawn.assert_not_called()
        kill.assert_not_called()

    def test_foreign_server_is_not_reused_or_stopped(self):
        self.speech.health = Mock(return_value={'settings': '/another/profile', 'ready': True})
        with self.assertRaisesRegex(RuntimeError, 'Another speech service'):
            self.speech.start()
        self.assertIsNone(self.speech.process)

    def test_start_and_stop_owned_instance_uses_private_control_protocol(self):
        self.speech.binary.parent.mkdir()
        self.speech.binary.touch()
        process = Mock(pid=999999)
        process.poll.side_effect = [None, 0]
        self.speech.health = Mock(side_effect=lambda: None if self.speech.instance is None else {
            'ready': True, 'instance': self.speech.instance})
        with patch('ou_dedetai.opensapi.subprocess.Popen', return_value=process) as spawn, \
                patch('ou_dedetai.opensapi.subprocess.run') as run:
            self.speech.start()
            self.assertIn('--serve', spawn.call_args.args[0])
            self.assertEqual(self.speech.settings.with_suffix('.control').stat().st_mode & 0o777, 0o600)
            self.speech.stop()
            self.assertIn('--stop-server', run.call_args.args[0])
        self.assertIsNone(self.speech.process)

    def test_install_passes_selected_prefix_and_wine_without_shell(self):
        self.speech.binary.parent.mkdir()
        self.speech.binary.touch()
        with patch('ou_dedetai.opensapi.subprocess.run') as run, patch('ou_dedetai.opensapi.subprocess.Popen'):
            self.speech.configure()
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('--wine-prefix') + 1], self.app.conf.wine_prefix)
        self.assertEqual(args[args.index('--wine') + 1], self.app.conf.wine_binary)
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_config_preference_survives_legacy_environment_defaults(self):
        path = self.root / 'config.json'
        path.write_text(json.dumps({'speech_enabled': True}))
        with patch.object(LegacyConfiguration, 'load_from_env', return_value=LegacyConfiguration()):
            config = PersistentConfiguration.load_from_path(str(path))
        self.assertTrue(config.speech_enabled)
        conf = object.__new__(Config)
        conf._raw = config
        conf._write = Mock()
        conf.speech_enabled = False
        self.assertFalse(conf.speech_enabled)
        conf._write.assert_called_once()


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
