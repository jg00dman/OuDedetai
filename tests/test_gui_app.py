import unittest
from types import MethodType
from unittest.mock import Mock, patch

from ou_dedetai.gui_app import ControlWindow, InstallerWindow


class SpeechControlsTests(unittest.TestCase):
    def window(self, installed=False):
        window = Mock()
        window.is_installed.return_value = installed
        window._speech_install_ready = True
        window.update_speech_controls = MethodType(ControlWindow.update_speech_controls, window)
        window.root.after.side_effect = lambda delay, callback: callback()
        window.start_thread.side_effect = lambda callback: callback()
        return window

    def assert_disabled(self, window, disabled):
        state = 'disabled' if disabled else '!disabled'
        window.gui.speech_checkbox.state.assert_called_with([state])
        window.gui.speech_configure.state.assert_called_with([state])

    def test_controls_follow_installed_state(self):
        window = self.window()
        window.update_speech_controls()
        self.assert_disabled(window, True)
        window.is_installed.return_value = True
        window.update_speech_controls()
        self.assert_disabled(window, False)
        window.is_installed.return_value = False
        window.update_speech_controls()
        self.assert_disabled(window, True)

    def test_both_install_paths_wait_for_success_even_if_exe_already_exists(self):
        for advanced in (False, True):
            for failure in (False, True):
                with self.subTest(advanced=advanced, failure=failure):
                    window = self.window()
                    def install(app):
                        app.is_installed.return_value = True  # MSI finished; remaining setup is not done.
                        app.update_speech_controls()
                        self.assert_disabled(app, True)
                        if failure:
                            raise RuntimeError('Remaining setup failed')
                    def run():
                        if advanced:
                            dialog = Mock(app=window, start_thread=window.start_thread)
                            InstallerWindow.start_install_thread(dialog)
                        else:
                            ControlWindow.run_install(window)
                    with patch('ou_dedetai.gui_app.installer.install', side_effect=install):
                        if failure:
                            with self.assertRaisesRegex(RuntimeError, 'Remaining setup failed'):
                                run()
                        else:
                            run()
                    self.assert_disabled(window, failure)
