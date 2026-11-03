import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, PropertyMock, patch

from ou_dedetai import constants, runtime, wine
from ou_dedetai.app import UserExitedFromAsk
from ou_dedetai.config import Config, EphemeralConfiguration, LegacyConfiguration, PersistentConfiguration
from ou_dedetai.logos import State


class TestRuntimeSelection(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.install = self.root / 'install'
        self.install.mkdir()
        self.config_path = self.root / 'config.json'
        self.app = Mock()
        self.app.choose_runtime.side_effect = lambda question, options, current: self.app.ask(question, options)
        self.app.choose_file.side_effect = lambda question, **kwargs: self.app.ask(
            question, [constants.PROMPT_OPTION_FILE])
        self.app._wine_selection_lock = threading.Lock()
        self.app.logos.existing_processes = {}
        self.app.logos.logos_state = State.STOPPED
        self.app.logos.indexing_state = State.STOPPED
        self.conf = object.__new__(Config)
        self.app.conf = self.conf
        self.conf.app = self.app
        self.conf._raw = PersistentConfiguration(install_dir=str(self.install), faithlife_product='Logos',
                                                faithlife_product_version='10', wine_binary='/old/wine')
        self.conf._overrides = EphemeralConfiguration.from_legacy(
            LegacyConfiguration(CONFIG_FILE=str(self.config_path)))
        self.conf._installed_faithlife_product_release = '40.0.0.0'
        self.conf._wine64_path = '/old/wine64'
        self.managed = Path(self.conf.installer_binary_dir)
        self.managed.mkdir(parents=True)
        recommended = patch.object(Config, 'wine_appimage_recommended_file_name',
                                   new_callable=PropertyMock, return_value='recommended.AppImage')
        recommended.start()
        self.addCleanup(recommended.stop)
        url = patch.object(Config, 'wine_appimage_recommended_url', new_callable=PropertyMock,
                           return_value='https://example.invalid/recommended.AppImage')
        url.start()
        self.addCleanup(url.stop)
        from ou_dedetai import network
        self.conf._network = Mock()
        self.conf._network.wine_runtime_releases.return_value = network.GithubSoftwareReleasesInfo(
            network.SoftwareReleaseInfo('10.0', 'https://example.invalid/stable.tar.xz'),
            network.SoftwareReleaseInfo('10.1', 'https://example.invalid/testing.tar.xz', prerelease=True))

    def executable(self, path, version='wine-10.0'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#!/bin/sh\nprintf "%s\\n" "{version}"\n')
        path.chmod(0o755)
        return path

    def image(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\x7fELF' + bytes(4) + b'AI\x02' + bytes(20))
        path.chmod(0o644)
        return path

    def activate_image(self, path):
        with patch.object(runtime, '_check_version'):
            runtime.activate_runtime(self.app, path)

    def test_downloaded_image_is_executable_selected_and_persisted(self):
        source = self.image(self.root / 'Downloads/wine.AppImage')
        self.activate_image(source)
        installed = self.managed / source.name
        self.assertTrue(os.access(installed, os.X_OK))
        self.assertFalse(os.access(source, os.X_OK))
        self.assertEqual(self.conf.wine_binary, str(installed))
        self.assertEqual(Path(self.conf.wine64_binary).resolve(), installed)
        self.assertEqual(Path(self.conf.wineserver_binary).resolve(), installed)
        data = json.loads(self.config_path.read_text())
        self.assertEqual(self.install / data['wine_binary'], installed)
        self.conf._raw = PersistentConfiguration.load_from_path(str(self.config_path))
        self.assertEqual(self.conf.wine_binary, str(installed))
        self.assertEqual(self.conf.wineserver_binary, str(self.managed / 'wineserver'))

    def test_existing_image_switch_updates_all_links(self):
        first = self.image(self.managed / 'first.AppImage')
        second = self.image(self.managed / 'second.AppImage')
        self.activate_image(first)
        self.activate_image(second)
        for name in ('wine', 'wine64', 'wineserver', 'winetricks', self.conf.wine_appimage_link_file_name):
            self.assertEqual((self.managed / name).resolve(), second)
        self.assertTrue(first.exists())

    def test_system_wine_without_wine64(self):
        binary = self.executable(self.root / 'system/bin/wine')
        server = self.executable(binary.parent / 'wineserver')
        runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf.wine64_binary, str(binary))
        self.assertEqual(self.conf.wineserver_binary, str(server))
        self.assertEqual(wine.get_wine_env(self.app)['WINE'], str(binary))
        self.assertEqual(wine.get_wine_env(self.app)['WINESERVER'], str(server))

    def test_custom_build_server_layout(self):
        binary = self.executable(self.root / 'build/loader/wine')
        server = self.executable(self.root / 'build/server/wineserver')
        runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf.wineserver_binary, str(server))

    def test_explicit_server_and_path_with_spaces(self):
        binary = self.executable(self.root / 'my build/wine')
        server = self.executable(self.root / 'separate server/wineserver')
        runtime.activate_runtime(self.app, binary, server)
        self.assertEqual(self.conf.wineserver_binary, str(server))

    def test_external_prefix_similar_to_install_is_not_relativised(self):
        binary = self.executable(self.root / 'install-custom/wine')
        self.executable(binary.parent / 'wineserver')
        runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf._raw.wine_binary, str(binary))

    def test_image_to_local_and_back(self):
        image = self.image(self.managed / 'wine.AppImage')
        self.activate_image(image)
        binary = self.executable(self.root / 'local/wine')
        server = self.executable(binary.parent / 'wineserver')
        runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf.wine_binary, str(binary))
        self.assertEqual(self.conf.wineserver_binary, str(server))
        self.activate_image(image)
        self.assertEqual(self.conf.wine_binary, str(image))

    def test_validation_failure_preserves_previous_selection(self):
        source = self.image(self.root / 'Downloads/new.AppImage')
        with patch.object(runtime, '_check_version', side_effect=ValueError('bad runtime')):
            with self.assertRaises(ValueError):
                runtime.activate_runtime(self.app, source)
        self.assertEqual(self.conf.wine_binary, '/old/wine')
        self.assertFalse((self.managed / source.name).exists())

    def test_save_failure_restores_links_and_selection(self):
        old = self.image(self.managed / 'old.AppImage')
        self.activate_image(old)
        before = self.config_path.read_bytes()
        new = self.image(self.root / 'Downloads/new.AppImage')
        with patch.object(self.conf, 'select_wine_runtime', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.activate_image(new)
        self.assertEqual(self.conf.wine_binary, str(old))
        self.assertEqual((self.managed / 'wine').resolve(), old)
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertFalse((self.managed / new.name).exists())

    def test_second_config_write_failure_rolls_back_first(self):
        binary = self.executable(self.root / 'local/wine')
        self.executable(binary.parent / 'wineserver')
        original = b'{"wine_binary": "/old/wine"}'
        self.config_path.write_bytes(original)
        replace = os.replace
        portable = self.install / f'{constants.BINARY_NAME}.json'
        def fail_portable(source, target):
            if Path(target) == portable:
                raise OSError('read-only portable config')
            return replace(source, target)
        with patch('ou_dedetai.config.os.replace', side_effect=fail_portable):
            with self.assertRaises(OSError):
                runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.config_path.read_bytes(), original)
        self.assertEqual(self.conf.wine_binary, '/old/wine')

    def test_cancel_menu_changes_nothing(self):
        self.app.ask.return_value = 'Cancel'
        runtime.select_runtime(self.app)
        self.assertEqual(self.conf.wine_binary, '/old/wine')
        self.assertFalse(self.config_path.exists())

    def test_cancel_file_dialog_changes_nothing(self):
        self.app.ask.side_effect = ['Custom…', UserExitedFromAsk(), 'Cancel']
        runtime.select_runtime(self.app)
        self.assertFalse(self.config_path.exists())

    def test_unknown_version_requires_confirmation(self):
        binary = self.executable(self.root / 'local/wine', 'wine-99.1 custom')
        self.executable(binary.parent / 'wineserver')
        self.app.approve.return_value = False
        with self.assertRaises(UserExitedFromAsk):
            runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf.wine_binary, '/old/wine')
        self.app.approve.return_value = True
        runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf.wine_binary, str(binary))

    def test_running_indexer_blocks_switch(self):
        self.app.logos.existing_processes = {'indexer': [Mock()]}
        with self.assertRaises(ValueError):
            runtime.activate_runtime(self.app, Path('/anything'))
        self.assertFalse(self.config_path.exists())

    def test_existing_non_symlink_is_not_overwritten(self):
        (self.managed / 'wine').write_text('preserve me')
        source = self.image(self.root / 'Downloads/new.AppImage')
        with self.assertRaises(ValueError):
            self.activate_image(source)
        self.assertEqual((self.managed / 'wine').read_text(), 'preserve me')
        self.assertEqual(self.conf.wine_binary, '/old/wine')

    def test_discovery_includes_wine_and_external_steam_library(self):
        local = self.executable(self.root / 'local/bin/wine')
        home = self.root / 'home'
        manifest = home / '.local/share/Steam/steamapps/libraryfolders.vdf'
        manifest.parent.mkdir(parents=True)
        library = self.root / 'extra library'
        manifest.write_text(f'"libraryfolders" {{ "1" {{ "path" "{library}" }} }}')
        proton = self.executable(library / 'steamapps/common/Proton 10/files/bin/wine')
        image = self.image(self.managed / 'installed.AppImage')
        with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {'PATH': str(local.parent)}):
            found = runtime.discover_runtimes(self.app)
        self.assertIn(local, found['System/local Wine'])
        self.assertIn(proton, found['Local Proton'])
        self.assertIn(image, found['Installed AppImages'])


    def test_non_executable_local_wine_is_rejected(self):
        binary = self.executable(self.root / 'custom/wine')
        binary.chmod(0o644)
        with self.assertRaises(ValueError):
            runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf.wine_binary, '/old/wine')

    def test_same_named_download_does_not_overwrite_installed_image(self):
        old = self.image(self.managed / 'same.AppImage')
        self.activate_image(old)
        before = old.read_bytes()
        new = self.image(self.root / 'Downloads/same.AppImage')
        new.write_bytes(before + b'different build')
        with self.assertRaises(ValueError):
            self.activate_image(new)
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(self.conf.wine_binary, str(old))

    def test_timeout_preserves_selection(self):
        import subprocess
        binary = self.executable(self.root / 'custom/wine')
        self.executable(binary.parent / 'wineserver')
        with patch.object(runtime.subprocess, 'run', side_effect=subprocess.TimeoutExpired('wine', 15)):
            with self.assertRaises(subprocess.TimeoutExpired):
                runtime.activate_runtime(self.app, binary)
        self.assertEqual(self.conf.wine_binary, '/old/wine')


    def test_version_probe_timeout_is_unknown_not_missing(self):
        import subprocess
        with patch.object(runtime.subprocess, 'run', side_effect=subprocess.TimeoutExpired('wine', 3)) as run:
            self.assertEqual(runtime.runtime_version(Path('/wine')), 'version unknown')
        self.assertEqual(run.call_args.kwargs['timeout'], 3)

    def test_version_probe_reports_version(self):
        binary = self.executable(self.root / 'wine', 'wine-10.0 (Staging)')
        self.assertEqual(runtime.runtime_version(binary), 'wine-10.0 (Staging)')


    def test_recommended_download_uses_installer_flow_then_activates(self):
        from ou_dedetai import installer, network
        self.conf._download_dir = str(self.root / 'cache')
        self.conf._user_download_dir = str(self.root / 'Downloads')
        Path(self.conf.download_dir).mkdir()
        name = 'recommended.AppImage'
        url = 'https://example.invalid/' + name
        option = runtime.RuntimeOption(name, self.managed / name, recommended=True, download_url=url)
        def download(source, target=None, app=None):
            self.assertEqual(source, url)
            self.assertEqual(self.conf.wine_binary, '/old/wine')
            self.image(target)
        with patch.object(network, '_net_get', side_effect=download), \
                patch.object(network, '_verify_downloaded_file', return_value=True) as verify, \
                patch.object(installer, 'download_appimage', wraps=installer.download_appimage) as shared, \
                patch.object(runtime, '_check_version'):
            runtime.activate_option(self.app, option)
        shared.assert_called_once()
        verify.assert_called_once()
        self.assertTrue(os.access(self.managed / name, os.X_OK))
        self.assertEqual(self.conf.wine_binary, str(self.managed / name))
        self.assertTrue(self.config_path.exists())

    def test_failed_download_is_recoverable_and_preserves_selection(self):
        from ou_dedetai import network
        self.conf._download_dir = str(self.root / 'cache')
        self.conf._user_download_dir = str(self.root / 'Downloads')
        Path(self.conf.download_dir).mkdir()
        option = runtime.RuntimeOption('recommended.AppImage', self.managed / 'recommended.AppImage',
                                       download_url='https://example.invalid/image')
        def download(source, target=None, app=None):
            target.write_bytes(b'bad download')
        with patch.object(network, '_net_get', side_effect=download), \
                patch.object(network, '_verify_downloaded_file', return_value=False), \
                patch.object(runtime, 'activate_runtime') as activate:
            with self.assertRaisesRegex(ValueError, 'Bad file size or checksum'):
                runtime.activate_option(self.app, option)
        activate.assert_not_called()
        self.app.exit.assert_not_called()
        self.assertEqual(self.conf.wine_binary, '/old/wine')
        self.assertFalse(self.config_path.exists())
        self.assertFalse(option.path.exists())


    def test_running_logos_blocks_download(self):
        option = runtime.RuntimeOption('recommended.AppImage', self.managed / 'recommended.AppImage',
                                       download_url='https://example.invalid/image')
        self.app.logos.existing_processes = {'logos': [Mock()]}
        with patch('ou_dedetai.installer.download_appimage') as download:
            with self.assertRaises(ValueError):
                runtime.activate_option(self.app, option)
        download.assert_not_called()

    def preinstall(self):
        self.app.is_installed.return_value = False
        self.conf._raw.faithlife_product = None
        self.conf._raw.faithlife_product_version = None
        self.conf._raw.install_dir = None
        self.conf._raw.wine_binary = None
        self.conf._download_dir = str(self.root / 'cache')


    def bundle(self, name='custom bundle'):
        directory = self.root / name
        self.executable(directory / 'bin/wine')
        self.executable(directory / 'bin/wineserver')
        (directory / 'lib').mkdir()
        (directory / 'lib/support.so').write_bytes(b'keep full bundle layout')
        return directory

    def test_custom_extracted_directory_is_activated(self):
        directory = self.bundle()
        runtime.activate_runtime(self.app, directory)
        self.assertEqual(self.conf.wine_binary, str(directory / 'bin/wine'))
        self.assertEqual(self.conf.wineserver_binary, str(directory / 'bin/wineserver'))
        self.assertEqual((self.managed / 'wine').resolve(), directory / 'bin/wine')

    def test_bundle_archive_is_extracted_and_persisted(self):
        import tarfile
        directory = self.bundle()
        archive = self.root / 'build.bundle.tar.xz'
        with tarfile.open(archive, 'w:xz') as tar:
            tar.add(directory, arcname='wine-build')
        runtime.activate_runtime(self.app, archive)
        selected = Path(self.conf.wine_binary)
        self.assertTrue(selected.is_relative_to(self.conf.wine_distribution_dir))
        self.assertTrue((selected.parent.parent / 'lib/support.so').is_file())
        self.assertEqual((self.managed / 'wine').resolve(), selected)
        self.conf._raw = PersistentConfiguration.load_from_path(str(self.config_path))
        self.assertEqual(self.conf.wine_binary, str(selected))
        self.assertEqual(self.conf.wine_path_in_distribution, str(selected))

    def test_archive_with_path_traversal_is_rejected(self):
        import io
        import tarfile
        archive = self.root / 'bad.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            member = tarfile.TarInfo('../outside')
            member.size = 1
            tar.addfile(member, io.BytesIO(b'x'))
        with self.assertRaises(tarfile.FilterError):
            runtime.activate_runtime(self.app, archive)
        self.assertEqual(self.conf.wine_binary, '/old/wine')
        self.assertFalse((self.root / 'outside').exists())

    def test_invalid_bundle_does_not_replace_working_runtime(self):
        import tarfile
        old = self.bundle()
        runtime.activate_runtime(self.app, old)
        archive = self.root / 'empty.tar.xz'
        with tarfile.open(archive, 'w:xz'):
            pass
        with self.assertRaises(ValueError):
            runtime.activate_runtime(self.app, archive)
        self.assertEqual(self.conf.wine_binary, str(old / 'bin/wine'))
        self.assertEqual(list(Path(self.conf.wine_distribution_dir).iterdir()), [])

    def test_switching_appimage_to_bundle_removes_stale_appimage_links(self):
        self.activate_image(self.image(self.root / 'wine.AppImage'))
        directory = self.bundle()
        runtime.activate_runtime(self.app, directory)
        self.assertFalse((self.managed / self.conf.wine_appimage_link_file_name).is_symlink())
        self.assertFalse((self.managed / 'winetricks').is_symlink())
        self.assertEqual((self.managed / 'wineserver').resolve(), directory / 'bin/wineserver')

    def test_managed_release_metadata_survives_reload(self):
        from ou_dedetai.network import SoftwareReleaseInfo
        directory = self.bundle()
        release = SoftwareReleaseInfo('11.20-test', 'https://example.invalid/build.bundle.tar.xz',
                                      '2026-10-30T00:00:00Z', True)
        runtime.activate_runtime(self.app, directory, release=release)
        loaded = PersistentConfiguration.load_from_path(str(self.config_path))
        self.assertEqual(loaded.wine_runtime_version, release.version)
        self.assertTrue(loaded.wine_runtime_prerelease)
        self.assertEqual(loaded.wine_runtime_published_at, release.published_at)

    def test_verification_stamp_is_saved_to_both_config_files(self):
        self.conf.mark_installation_verified()
        portable = self.install / f'{constants.BINARY_NAME}.json'
        for path in (self.config_path, portable):
            self.assertEqual(json.loads(path.read_text())['last_verified_od_version'], constants.LLI_CURRENT_VERSION)

    def test_before_install_choice_is_recorded_without_downloading(self):
        self.preinstall()
        option = runtime.RuntimeOption(constants.WINE_BETA_SIGIL, None, choice=constants.WINE_BETA_SIGIL)
        with patch('ou_dedetai.installer.download_appimage') as download:
            runtime.activate_option(self.app, option)
        download.assert_not_called()
        self.assertEqual(self.conf._raw.wine_binary, constants.WINE_BETA_SIGIL)
        self.assertIsNone(self.conf._raw.install_dir)
    def test_old_managed_loader_symlink_is_resolved_before_relinking(self):
        image = self.image(self.root / 'old.AppImage')
        self.activate_image(image)
        selected = Path(self.conf.wine_binary)
        self.conf._raw.wine_binary = str(self.managed / 'wine64')
        self.activate_image(self.managed / 'wine64')
        self.assertEqual((self.managed / 'wine64').resolve(strict=True), selected)
        self.assertEqual(self.conf.wine_binary, str(selected))

    def test_similar_install_prefix_is_not_made_relative_by_setter(self):
        path = str(self.install) + '-custom/bin/wine'
        self.conf.wine_binary = path
        self.assertEqual(self.conf._raw.wine_binary, path)
