import unittest
from unittest.mock import Mock, patch
from ou_dedetai import constants
from ou_dedetai.gui_app import ControlWindow, GuiApp


class TestRuntimeMenu(unittest.TestCase):
    def test_combined_update_is_disabled_without_updates(self):
        from ou_dedetai.updates import UpdatePlan
        window = Mock()
        window._available_updates = UpdatePlan()
        window._updates_busy = False
        with patch('ou_dedetai.gui_app.gui.ToolTip'):
            ControlWindow.update_combined_button(window)
        window.gui.update_lli_button.state.assert_called_once_with(['disabled'])
        window.gui.set_appimage_button.state.assert_called_once_with(['!disabled'])

    def test_picker_opens_on_tk_thread(self):
        window = Mock()
        with patch('ou_dedetai.runtime_gui.RuntimePicker') as picker:
            ControlWindow.set_appimage(window)
        picker.assert_called_once_with(window)
        window.start_thread.assert_not_called()

    def test_file_dialog_cancel_is_cancel(self):
        with patch('ou_dedetai.gui_app.fd.askopenfilename', return_value=''):
            self.assertIsNone(GuiApp._ask(Mock(), 'Choose runtime', constants.PROMPT_OPTION_FILE))

    def test_combined_update_lists_all_components(self):
        from ou_dedetai.updates import UpdatePlan
        from ou_dedetai.runtime import RuntimeOption
        window = Mock()
        window._available_updates = UpdatePlan(od=True, runtime=RuntimeOption('Bundle', None), logos='50')
        window._updates_busy = False
        with patch('ou_dedetai.gui_app.gui.ToolTip'):
            ControlWindow.update_combined_button(window)
        window.gui.update_lli_label.config.assert_called_once_with(text='Updates: OD, Runtime, Logos')
        window.gui.update_lli_button.state.assert_called_once_with(['!disabled'])
