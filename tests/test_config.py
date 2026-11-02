import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ou_dedetai.config import PersistentConfiguration


class PiperConfigurationTests(unittest.TestCase):
    def test_enabled_and_paths_survive_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'piper_enabled': True, 'piper_binary': '/piper/bin',
                                        'piper_model': '/voices/test.onnx'}))
            with patch.dict('os.environ', {}, clear=True):
                config = PersistentConfiguration.load_from_path(str(path))
            self.assertTrue(config.piper_enabled)
            self.assertEqual(config.piper_binary, '/piper/bin')
            self.assertEqual(config.piper_model, '/voices/test.onnx')

    def test_old_configuration_keeps_feature_disabled(self):
        self.assertFalse(PersistentConfiguration().piper_enabled)
