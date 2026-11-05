import threading
import unittest
from unittest.mock import Mock, patch

from types import SimpleNamespace
from ou_dedetai.gui_app import GuiApp, ControlWindow, InstallerWindow


def _approve_on_worker(app, question):
    result = {}

    def worker():
        result["answer"] = GuiApp.approve(app, question)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "approve() hung on worker thread"
    return result["answer"]


class TestGuiAppApprove(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        # Run scheduled callbacks immediately, standing in for the mainloop
        self.app.root.after.side_effect = lambda _delay, fn: fn()
        self.app._run_on_main_thread = lambda fn: GuiApp._run_on_main_thread(self.app, fn)

    @patch("ou_dedetai.gui_app.messagebox.askquestion", return_value="yes")
    def test_main_thread_calls_dialog_directly(self, askquestion):
        self.assertTrue(GuiApp.approve(self.app, "Q?", "ctx"))
        self.app.root.after.assert_not_called()
        askquestion.assert_called_once_with("Q?", "Q?\n\nctx")

    @patch("ou_dedetai.gui_app.messagebox.askquestion", side_effect=["yes", "no"])
    def test_worker_thread_marshals_answer(self, askquestion):
        self.assertTrue(_approve_on_worker(self.app, "Q?"))
        self.assertFalse(_approve_on_worker(self.app, "Q?"))
        self.assertEqual(self.app.root.after.call_count, 2)

    def test_run_on_main_thread_reraises_on_worker(self):
        def boom():
            raise ValueError("x")

        raised = {}

        def worker():
            try:
                GuiApp._run_on_main_thread(self.app, boom)
            except ValueError as e:
                raised["e"] = e

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertIsInstance(raised.get("e"), ValueError)


class TestGuiAppAsk(unittest.TestCase):
    def setUp(self):
        self.app = Mock()

    @patch("ou_dedetai.gui_app.ChoicePopUp")
    def test_returns_chosen_option(self, popup_cls):
        def answer(_q, _opts, answer_q):
            answer_q.put("A")
            return Mock()

        popup_cls.side_effect = answer
        self.assertEqual(GuiApp._ask(self.app, "Q?", ["A", "B"]), "A")
        self.app.root.wait_window.assert_called_once()

    @patch("ou_dedetai.gui_app.ChoicePopUp")
    def test_closed_window_returns_none(self, popup_cls):
        self.assertIsNone(GuiApp._ask(self.app, "Q?", ["A", "B"]))
        self.app.root.wait_window.assert_called_once()


class TestRunnerSelection(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(ControlWindow)
        self.app.root = Mock()
        self.app.start_thread = lambda task: task()
        self.app.status = Mock()
        self.app.clear_status = Mock()
        self.app.conf = SimpleNamespace(wine_binary='/old/wine')

    @patch('ou_dedetai.gui_app.utils.get_wine_options', return_value=['Recommended Bundled'])
    def test_shared_options(self, options):
        self.assertEqual(self.app.runner_options(), ['Recommended Bundled', self.app._runner_file_option])
        window = object.__new__(InstallerWindow)
        window.app, window.conf = self.app, self.app.conf
        window.gui = Mock()
        window.gui.winevar.get.return_value = 'Recommended Bundled'
        window._post_dropdown_change = Mock()
        window.set_wine()
        self.assertEqual(self.app.conf.wine_binary, 'Recommended Bundled')
        window._post_dropdown_change.assert_called_once()

    @patch('ou_dedetai.gui_app.fd.askopenfilename', return_value='')
    def test_cancel_file_preserves_selection(self, dialog):
        self.assertFalse(self.app.select_runner(self.app._runner_file_option))
        self.assertEqual(self.app.conf.wine_binary, '/old/wine')

    @patch('ou_dedetai.gui_app.messagebox.showerror')
    @patch('ou_dedetai.gui_app.utils.check_appimage', return_value=False)
    @patch('ou_dedetai.gui_app.tarfile.is_tarfile', return_value=False)
    @patch('ou_dedetai.gui_app.fd.askopenfilename', return_value='/invalid.tar.gz')
    def test_invalid_file_preserves_selection(self, dialog, archive, image, error):
        self.assertFalse(self.app.select_runner(self.app._runner_file_option))
        self.assertEqual(self.app.conf.wine_binary, '/old/wine')
        error.assert_called_once()

    @patch('ou_dedetai.gui_app.utils.check_appimage', return_value=False)
    @patch('ou_dedetai.gui_app.tarfile.is_tarfile', return_value=True)
    @patch('ou_dedetai.gui_app.fd.askopenfilename', return_value='/custom.tar.gz')
    def test_select_local_tarball(self, dialog, archive, image):
        self.assertTrue(self.app.select_runner(self.app._runner_file_option))
        self.assertEqual(self.app.conf.wine_binary, '/custom.tar.gz')

    @patch('ou_dedetai.gui_app.system.ensure_winetricks')
    @patch('ou_dedetai.gui_app.wine.setup_wine')
    def test_installed_runner_uses_shared_selection_and_setup(self, setup, winetricks):
        self.app._ask = Mock(return_value='Recommended Bundled')
        self.app.runner_options = Mock(return_value=['Recommended Bundled'])
        self.app.update_latest_appimage_button = Mock()
        self.app.set_runner()
        self.app._ask.assert_called_once_with('Select Runner', self.app.runner_options())
        self.assertEqual(self.app.conf.wine_binary, 'Recommended Bundled')
        setup.assert_called_once_with(self.app)
        winetricks.assert_called_once_with(self.app)
