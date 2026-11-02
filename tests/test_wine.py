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
        self.assertEqual(env['APPIMAGE_EXTRACT_AND_RUN'], '1')

    def test_version_check_accepts_extraction_environment(self):
        from ou_dedetai.wine import get_wine_release
        env = {'APPIMAGE_EXTRACT_AND_RUN': '1'}
        with patch('ou_dedetai.wine.subprocess.check_output', return_value='wine-11.21\n') as run:
            release, reason = get_wine_release('/wine/AppImage', env=env)
        self.assertEqual(release.major, 11)
        self.assertEqual(release.minor, 21)
        self.assertEqual(run.call_args.kwargs['env'], env)
