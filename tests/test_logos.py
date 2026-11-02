import tempfile
import unittest
from unittest.mock import Mock, patch

from ou_dedetai.logos import LogosManager, State


class LogosSpeechLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Mock()
        self.app.conf.install_dir = self.temp.name
        self.app.conf.logos_exe = 'splash'
        self.app.conf.logos_system_exe_windows_path = 'main'
        self.app.conf.logos_cef_exe_windows_path = 'cef'
        self.manager = LogosManager(self.app)
        self.manager.piper = Mock()

    def test_splash_exit_does_not_stop_backend_while_main_runs(self):
        self.manager.logos_state = State.RUNNING
        self.manager.existing_processes = {'main': [Mock(is_running=lambda: True)]}
        self.manager.monitor_logos()
        self.manager.piper.stop.assert_not_called()

    def test_final_exit_stops_managed_backend(self):
        self.manager.logos_state = State.RUNNING
        with patch.object(self.manager, 'get_logos_pids'):
            self.manager.monitor_logos()
        self.manager.piper.stop.assert_called_once()
        self.assertEqual(self.manager.logos_state, State.STOPPED)

    def test_startup_gap_does_not_stop_backend(self):
        self.manager.logos_state = State.STARTING
        self.manager._launch_finished = True
        with patch('ou_dedetai.logos.time.monotonic', return_value=10):
            self.manager.monitor_logos()
        self.manager.piper.stop.assert_not_called()

    def test_failed_launch_eventually_stops_backend(self):
        self.manager.logos_state = State.STARTING
        self.manager._launch_finished = True
        with patch('ou_dedetai.logos.time.monotonic', return_value=61):
            self.manager.monitor_logos()
        self.manager.piper.stop.assert_called_once()
