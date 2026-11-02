import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ou_dedetai.piper import PiperManager, configure, disable, start


class PiperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Mock()
        self.app.conf.install_dir = self.temp.name
        self.app.conf.piper_model = str(Path(self.temp.name) / 'voice.onnx')
        self.app.conf.piper_binary = '/bin/true'
        self.app.conf.piper_enabled = False
        Path(self.app.conf.piper_model).touch()
        Path(self.app.conf.piper_model + '.json').write_text('{}')
        self.manager = PiperManager(self.app)

    def test_external_compatible_server_is_reused_and_not_stopped(self):
        with patch.object(self.manager, 'health', return_value={'model': 'voice.onnx'}), \
                patch('ou_dedetai.piper.subprocess.Popen') as spawn, patch('ou_dedetai.piper.os.killpg') as kill:
            self.manager.start()
            self.manager.stop()
            spawn.assert_not_called()
            kill.assert_not_called()

    def test_other_voice_is_not_reused(self):
        with patch.object(self.manager, 'health', return_value={'model': 'different.onnx'}):
            with self.assertRaisesRegex(RuntimeError, 'different voice'):
                self.manager.start()

    def test_missing_model_does_not_spawn(self):
        Path(self.app.conf.piper_model).unlink()
        with patch('ou_dedetai.piper.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'ONNX'):
                self.manager.start()
            spawn.assert_not_called()

    def test_reused_pid_is_never_killed(self):
        self.manager.directory.mkdir(parents=True)
        self.manager.record.write_text(json.dumps({'pid': 99, 'created': 1, 'instance': 'ours'}))
        with patch('ou_dedetai.piper.psutil.Process') as proc, patch('ou_dedetai.piper.os.killpg') as kill:
            proc.return_value.create_time.return_value = 2
            self.manager.stop()
            kill.assert_not_called()

    def test_matching_pid_without_our_instance_is_never_killed(self):
        self.manager.directory.mkdir(parents=True)
        self.manager.record.write_text(json.dumps({'pid': 99, 'created': 1, 'instance': 'ours'}))
        with patch('ou_dedetai.piper.psutil.Process') as proc, patch('ou_dedetai.piper.os.killpg') as kill:
            proc.return_value.create_time.return_value = 1
            proc.return_value.cmdline.return_value = ['other', '--instance', 'theirs']
            self.manager.stop()
            kill.assert_not_called()

    def test_only_owned_process_group_is_stopped(self):
        proc = Mock(pid=99)
        with patch.object(self.manager, 'owned_process', return_value=proc), \
                patch('ou_dedetai.piper.os.getpgid', return_value=99), \
                patch('ou_dedetai.piper.os.killpg') as kill:
            self.manager.stop()
            kill.assert_called_once()
            self.assertEqual(kill.call_args.args[0], 99)

    def test_start_failure_is_nonfatal(self):
        self.app.logos.piper.start.side_effect = RuntimeError('missing backend')
        start(self.app)
        self.assertIn('Logos can still run', self.app.status.call_args.args[0])

    def test_disable_persists_and_stops(self):
        disable(self.app)
        self.assertFalse(self.app.conf.piper_enabled)
        self.app.logos.piper.stop.assert_called_once()

    def test_configure_requires_closed_logos(self):
        from ou_dedetai.logos import State
        self.app.logos.logos_state = State.RUNNING
        configure(self.app)
        self.app.ask.assert_not_called()

    def test_install_rejects_checksum_without_extracting(self):
        import io
        from ou_dedetai.logos import State
        from ou_dedetai.piper import install
        self.app.logos.logos_state = State.STOPPED
        self.app.logos.piper = self.manager
        self.app.approve.return_value = True
        with patch('ou_dedetai.piper.urllib.request.urlopen', return_value=io.BytesIO(b'bad archive')), \
                patch('ou_dedetai.piper.tarfile.open') as extract:
            install(self.app)
        extract.assert_not_called()
        self.assertFalse(self.app.conf.piper_enabled)
        self.assertIn('checksum mismatch', self.app.status.call_args.args[0])

    def test_registration_targets_existing_prefix_and_preserves_parent_environment(self):
        from ou_dedetai.piper import register
        self.app.conf.wine_prefix = '/existing/Logos prefix'
        self.app.conf.wine_binary = '/custom/wine.AppImage'
        with patch('ou_dedetai.piper.subprocess.run', return_value=Mock(stdout='OpenSAPI')) as run, \
                patch.dict('os.environ', {'WINEDLLOVERRIDES': 'mscoree=n,b'}):
            register(self.app, '/backend/piper', '/voices/voice.onnx')
        self.assertTrue(self.app.conf.piper_enabled)
        self.assertEqual(run.call_args_list[1].kwargs['env']['WINEPREFIX'], '/existing/Logos prefix')
        self.assertEqual(run.call_args_list[1].kwargs['env']['WINEDLLOVERRIDES'], 'mscoree=n,b')
        self.assertIn('/reg:64', run.call_args_list[-1].args[0])
