import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ou_dedetai import constants, installer, network, runtime, utils, wine


class TestInstallerRuntimes(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.app._wine_selection_lock = threading.Lock()
        self.app.conf._raw.wine_binary = None
        self.app.conf.download_dir = '/cache'
        self.app.conf._overrides.installer_binary_dir = None
        self.app.conf._overrides.install_dir = None
        self.app.conf._raw.install_dir = None
        self.app.conf._network.wine_runtime_releases.side_effect = lambda format: network.GithubSoftwareReleasesInfo(
            network.SoftwareReleaseInfo('10.0', 'https://example.invalid/stable.' +
                                        ('AppImage' if format == 'appimage' else 'tar.xz')),
            network.SoftwareReleaseInfo('10.1', 'https://example.invalid/testing.' +
                                        ('AppImage' if format == 'appimage' else 'tar.xz'), prerelease=True))

    def test_installer_and_picker_share_the_same_choices(self):
        with patch.object(runtime, 'discover_runtimes', return_value={}), \
                patch.object(runtime.system, 'get_os', return_value=('debian', '12')):
            picker = runtime.runtime_options(self.app)
            choices = utils.get_wine_options(self.app)
        self.assertEqual(choices, [o.choice or str(o.path) for o in picker])
        self.assertEqual(choices[0], constants.WINE_RECOMMENDED_TARBALL_SIGIL)
        self.assertIn(constants.WINE_TESTING_TARBALL_SIGIL, choices)
        self.assertIn(constants.WINE_UNTESTED_STAGING_APPIMAGE_SIGIL, choices)

    def test_missing_testing_release_is_not_offered(self):
        self.app.conf._network.wine_runtime_releases.side_effect = None
        self.app.conf._network.wine_runtime_releases.return_value = network.GithubSoftwareReleasesInfo(
            network.SoftwareReleaseInfo('10.0', 'https://example.invalid/stable.tar.xz'), None)
        choices = [o.choice for o in runtime.standard_options(self.app)]
        self.assertNotIn(constants.WINE_TESTING_TARBALL_SIGIL, choices)
        self.assertNotIn(constants.WINE_TESTING_APPIMAGE_SIGIL, choices)

    def test_setup_uses_exact_selected_testing_asset(self):
        self.app.conf.wine_binary = constants.WINE_TESTING_TARBALL_SIGIL
        with patch.object(installer, 'download_appimage', return_value=Path('/cache/testing.tar.xz')) as download, \
                patch.object(runtime, 'activate_runtime') as activate:
            wine.setup_wine(self.app)
        self.assertEqual(download.call_args.args[1:], ('testing.tar.xz', 'https://example.invalid/testing.tar.xz'))
        self.assertTrue(activate.call_args.kwargs['release'].prerelease)

    def test_install_is_blocked_while_picker_is_open(self):
        self.app._wine_selection_lock.acquire()
        with patch.object(installer, '_install') as install:
            installer.install(self.app)
        install.assert_not_called()

    def test_install_releases_lock_after_failure(self):
        with patch.object(installer, '_install', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                installer.install(self.app)
        self.assertFalse(self.app._wine_selection_lock.locked())

    def test_verification_preserves_renderer_smoothing_and_font_choices(self):
        self.app.conf.skip_install_system_dependencies = True
        with patch.object(installer, 'create_wine_symlinks'), \
                patch.object(installer.system, 'ensure_winetricks'), \
                patch.object(wine, 'disable_winemenubuilder'), \
                patch.object(wine, 'get_renderer', return_value='vulkan'), \
                patch.object(wine, 'wine_reg_query', return_value='2'), \
                patch.object(wine, 'set_renderer') as renderer, \
                patch.object(wine, 'set_fontsmoothing_to_rgb') as smoothing, \
                patch.object(wine, 'configure_printing'), \
                patch.object(wine, 'install_fonts'), \
                patch.object(wine, 'set_font_replacements') as replacements, \
                patch.object(wine, 'enforce_icu_data_files'):
            installer.verify_installation(self.app)
        renderer.assert_not_called()
        smoothing.assert_not_called()
        self.assertTrue(replacements.call_args.kwargs['preserve_existing'])
    def test_custom_selection_does_not_require_download_metadata(self):
        self.app.conf.wine_binary = '/custom/wine'
        self.app.installer_step_count = 0
        self.app.conf.wine_download_url = property(lambda _: self.fail('Must not resolve a custom runtime URL'))
        installer.ensure_choices(self.app)
        self.app.conf._network.wine_runtime_releases.assert_not_called()
