import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ou_dedetai.config import Config, PersistentConfiguration


class TestRunnerConfig(unittest.TestCase):
    def test_distribution_path_follows_selected_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = object.__new__(Config)
            conf._raw = PersistentConfiguration(install_dir=tmp, faithlife_product='Logos')
            conf._overrides = SimpleNamespace(install_dir=None, installer_binary_dir=None)
            runner = Path(conf.wine_distribution_dir) / 'selected' / 'bin' / 'wine'
            runner.parent.mkdir(parents=True)
            runner.touch()
            conf._raw.wine_binary = str(runner)
            self.assertEqual(conf.wine_path_in_distribution, str(runner))
