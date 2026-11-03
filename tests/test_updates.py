import threading
import unittest
from unittest.mock import Mock, patch

from ou_dedetai import constants, network, runtime, updates
from ou_dedetai.config import PersistentConfiguration
from ou_dedetai.logos import State

BASE = 'https://github.com/FaithLife-Community/wine-appimages/releases/download/'


def release(version, date, testing=False):
    return network.SoftwareReleaseInfo(version, BASE + version + '/wine.bundle.tar.xz', date, testing)


class TestRuntimeUpdates(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.app._wine_selection_lock = threading.Lock()
        self.app.conf._raw = PersistentConfiguration(
            wine_binary='/installed/bin/wine', wine_binary_code='Bundle', wine_runtime_version='10.0',
            wine_runtime_url=BASE + '10.0/wine.bundle.tar.xz',
            wine_runtime_published_at='2026-10-01T00:00:00Z')
        self.app.conf.is_wine_binary_in_distribution = True
        self.app.conf.wine_appimage_path = None
        self.app.conf.download_dir = '/cache'
        self.app.logos.logos_state = self.app.logos.indexing_state = State.STOPPED
        self.app.logos.existing_processes = {}
        self.stable = release('10.0', '2026-10-01T00:00:00Z')
        self.testing = release('11.0', '2026-10-20T00:00:00Z', True)
        self.catalog(self.stable, self.testing)

    def catalog(self, stable, testing):
        self.app.conf._network.wine_runtime_releases.return_value = network.GithubSoftwareReleasesInfo(stable, testing)

    def test_release_user_is_offered_new_testing_build(self):
        option = updates.runtime_update(self.app)
        self.assertEqual(option.release, self.testing)
        self.assertTrue(option.prerelease)

    def test_testing_user_is_offered_new_testing_build(self):
        self.app.conf._raw.wine_runtime_prerelease = True
        self.app.conf._raw.wine_runtime_version = '10.5'
        self.app.conf._raw.wine_runtime_published_at = '2026-10-10T00:00:00Z'
        self.assertEqual(updates.runtime_update(self.app).release, self.testing)

    def test_new_release_is_preferred_to_new_testing_build(self):
        stable = release('10.1', '2026-10-15T00:00:00Z')
        self.catalog(stable, self.testing)
        self.assertEqual(updates.runtime_update(self.app).release, stable)

    def test_old_stable_does_not_downgrade_testing(self):
        raw = self.app.conf._raw
        raw.wine_runtime_version = self.testing.version
        raw.wine_runtime_url = self.testing.download_url
        raw.wine_runtime_published_at = self.testing.published_at
        raw.wine_runtime_prerelease = True
        self.assertIsNone(updates.runtime_update(self.app))

    def test_promoted_testing_release_is_offered_as_stable(self):
        raw = self.app.conf._raw
        raw.wine_runtime_version = self.testing.version
        raw.wine_runtime_url = self.testing.download_url
        raw.wine_runtime_published_at = self.testing.published_at
        raw.wine_runtime_prerelease = True
        stable = release(self.testing.version, self.testing.published_at)
        self.catalog(stable, None)
        self.assertFalse(updates.runtime_update(self.app).prerelease)

    def test_appimage_install_checks_appimage_assets(self):
        self.app.conf.wine_appimage_path = '/installed/wine.AppImage'
        updates.runtime_update(self.app, refresh=True)
        self.app.conf._network.wine_runtime_releases.assert_called_once_with('appimage', refresh=True)

    def test_custom_runtime_offers_recommended_bundle(self):
        self.app.conf._raw.wine_binary_code = 'Custom'
        self.app.conf.wine_appimage_path = '/custom.AppImage'
        option = updates.runtime_update(self.app)
        self.assertEqual(option.release, self.stable)
        self.app.conf._network.wine_runtime_releases.assert_called_once_with('bundle', refresh=False)

    def test_only_od_updates_until_restart(self):
        plan = updates.UpdatePlan(True, runtime.RuntimeOption('New bundle', None), '51')
        with patch.object(updates, 'check_updates', return_value=plan), \
                patch.object(updates, 'verify_installation') as verify, \
                patch.object(updates.utils, 'update_to_latest_lli_release') as od, \
                patch.object(runtime, 'activate_option') as activate, \
                patch.object(updates.installer, '_install') as logos:
            updates.update_all(self.app)
        od.assert_called_once_with(self.app)
        verify.assert_not_called()
        activate.assert_not_called()
        logos.assert_not_called()

    def test_runtime_finishes_before_logos(self):
        option = updates.runtime_update(self.app)
        plan = updates.UpdatePlan(runtime=option, logos='51')
        order = []
        with patch.object(updates, 'check_updates', return_value=plan), \
                patch.object(updates, 'verify_installation', return_value=True), \
                patch.object(runtime, 'activate_option', side_effect=lambda *a: order.append('runtime')), \
                patch.object(updates.installer, '_install', side_effect=lambda *a: order.append('logos')):
            updates.update_all(self.app)
        self.assertEqual(order, ['runtime', 'logos'])

    def test_runtime_failure_stops_logos_update(self):
        plan = updates.UpdatePlan(runtime=updates.runtime_update(self.app), logos='51')
        with patch.object(updates, 'check_updates', return_value=plan), \
                patch.object(updates, 'verify_installation', return_value=True), \
                patch.object(runtime, 'activate_option', side_effect=ValueError('validation failed')), \
                patch.object(updates.installer, '_install') as logos:
            updates.update_all(self.app)
        logos.assert_not_called()
        self.assertFalse(self.app._wine_selection_lock.locked())
        self.assertIn('Update stopped', self.app.info.call_args.args[0])

    def test_declining_custom_replacement_can_still_update_logos(self):
        self.app.conf._raw.wine_binary_code = 'Custom'
        self.app.approve.side_effect = [True, False]
        plan = updates.UpdatePlan(runtime=updates.runtime_update(self.app), logos='51')
        with patch.object(updates, 'check_updates', return_value=plan), \
                patch.object(updates, 'verify_installation', return_value=True), \
                patch.object(runtime, 'activate_option') as activate, \
                patch.object(updates.installer, '_install') as logos:
            updates.update_all(self.app)
        activate.assert_not_called()
        logos.assert_called_once()
        self.assertIn('custom runtime', self.app.approve.call_args.args[0])

    def test_verification_only_once_for_this_od_version(self):
        self.app.conf._raw.last_verified_od_version = constants.LLI_CURRENT_VERSION
        with patch.object(updates.installer, 'verify_installation') as maintenance:
            self.assertTrue(updates.verify_installation(self.app))
        maintenance.assert_not_called()

    def test_verification_marks_version_only_after_success(self):
        order = []
        self.app.conf.mark_installation_verified.side_effect = lambda: order.append('saved')
        with patch.object(updates.installer, 'verify_installation', side_effect=lambda *a: order.append('verified')):
            self.assertTrue(updates.verify_installation(self.app))
        self.assertEqual(order, ['verified', 'saved'])

    def test_failed_verification_is_not_marked_and_is_retried(self):
        with patch.object(updates.installer, 'verify_installation', side_effect=ValueError('failed')) as maintenance:
            self.assertFalse(updates.verify_installation(self.app))
            self.assertFalse(updates.verify_installation(self.app))
        self.assertEqual(maintenance.call_count, 2)
        self.app.conf.mark_installation_verified.assert_not_called()

    def test_verification_failure_blocks_runtime_and_logos(self):
        plan = updates.UpdatePlan(runtime=updates.runtime_update(self.app), logos='51')
        with patch.object(updates, 'check_updates', return_value=plan), \
                patch.object(updates, 'verify_installation', return_value=False), \
                patch.object(runtime, 'activate_option') as activate, \
                patch.object(updates.installer, '_install') as logos:
            updates.update_all(self.app)
        activate.assert_not_called()
        logos.assert_not_called()
    def test_recommended_appimage_fallback_keeps_preferring_bundles(self):
        raw = self.app.conf._raw
        raw.wine_binary_code = 'BundleFallback'
        raw.wine_runtime_url = BASE + '10.0/wine.AppImage'
        self.app.conf.wine_appimage_path = '/installed/wine.AppImage'
        self.catalog(self.stable, None)
        option = updates.runtime_update(self.app)
        self.app.conf._network.wine_runtime_releases.assert_called_once_with('bundle', refresh=False)
        self.assertEqual(option.release, self.stable)
