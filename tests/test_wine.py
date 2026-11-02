import unittest
from unittest.mock import Mock, patch
from ou_dedetai.wine import get_wine_env


class PiperWineEnvironmentTests(unittest.TestCase):
    def test_piper_override_preserves_native_dotnet_and_other_overrides(self):
        app = Mock()
        app.conf.wine_binary = '/wine/wine64'
        app.conf.wine_debug = '-all'
        app.conf.wine_dll_overrides = 'mscoree=n,b;winemenubuilder.exe=d'
        app.conf.wine_prefix = '/prefix'
        app.conf.wineserver_binary = '/wine/wineserver'
        app.conf.piper_enabled = True
        with patch('ou_dedetai.wine.system.fix_ld_library_path', side_effect=lambda value: value):
            env = get_wine_env(app)
        self.assertEqual(env['WINEDLLOVERRIDES'], 'mscoree=n,b;winemenubuilder.exe=d;sapi=b')
        self.assertEqual(env['WINEPREFIX'], '/prefix')
