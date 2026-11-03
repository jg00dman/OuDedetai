import json
import unittest
from unittest.mock import patch

from ou_dedetai import network

REPO = 'FaithLife-Community/wine-appimages'


def release(name, date, assets, testing=False, **kwargs):
    return dict(tag_name=name, published_at=date, updated_at=kwargs.pop('updated_at', date),
                prerelease=testing, assets=[{'browser_download_url': 'https://example.invalid/' + a}
                                           for a in assets], **kwargs)


class TestRuntimeReleaseAssets(unittest.TestCase):
    def fetch(self, releases, suffix):
        with patch.object(network, '_net_get', return_value=json.dumps(releases).encode()):
            return network._get_runtime_release_data(REPO, asset_suffix=suffix)

    def test_selects_bundle_and_appimage_by_format_not_asset_order(self):
        data = [release('10.0', '2026-10-01T00:00:00Z', ['checksums.txt', 'wine.AppImage', 'wine.tar.xz'])]
        self.assertTrue(self.fetch(data, ('.tar.xz', '.tgz', '.tar.gz')).latest.download_url.endswith('.tar.xz'))
        self.assertTrue(self.fetch(data, '.AppImage').latest.download_url.endswith('.AppImage'))

    def test_stable_and_testing_are_independent_and_drafts_excluded(self):
        data = [release('11.0', '2026-11-01T00:00:00Z', ['draft.tar.xz'], draft=True),
                release('10.2', '2026-10-25T00:00:00Z', ['pre.tar.xz'], True),
                release('10.1', '2026-10-20T00:00:00Z', ['stable.tar.xz']),
                release('10.0', '2026-10-10T00:00:00Z', ['old.tar.xz'], True)]
        catalog = self.fetch(data, '.tar.xz')
        self.assertEqual(catalog.latest.version, '10.1')
        self.assertEqual(catalog.pre_release.version, '10.2')
        self.assertTrue(catalog.pre_release.prerelease)
        self.assertEqual(catalog.latest.published_at, '2026-10-20T00:00:00Z')

    def test_editing_old_release_does_not_make_it_latest(self):
        data = [release('10.0', '2026-09-01T00:00:00Z', ['old.tar.xz'], updated_at='2026-11-01T00:00:00Z'),
                release('10.1', '2026-10-01T00:00:00Z', ['new.tar.xz'])]
        self.assertEqual(self.fetch(data, '.tar.xz').latest.version, '10.1')

    def test_absent_matching_asset_and_testing_return_none(self):
        result = self.fetch([release('10.0', '2026-10-01T00:00:00Z', ['wine.AppImage'])], '.tar.xz')
        self.assertIsNone(result.latest)
        self.assertIsNone(result.pre_release)

    def test_refresh_rechecks_both_channels_and_keeps_metadata(self):
        requests = object.__new__(network.NetworkRequests)
        result = network.GithubSoftwareReleasesInfo(network.SoftwareReleaseInfo('10', 'url', 'date'), None)
        with patch.object(network, '_get_runtime_release_data', return_value=result) as fetch:
            self.assertIs(requests.wine_runtime_releases(), result)
            self.assertIs(requests.wine_runtime_releases(), result)
            self.assertEqual(fetch.call_count, 1)
            requests.wine_runtime_releases(refresh=True)
            self.assertEqual(fetch.call_count, 2)
    def test_recommendation_falls_back_to_same_stable_appimage_not_older_bundle(self):
        data = [release('10.1', '2026-10-01T00:00:00Z', ['wine.AppImage']),
                release('10.0', '2026-09-01T00:00:00Z', ['old.bundle.tar.xz'])]
        result = self.fetch(data, ('.bundle.tar.xz', '.AppImage'))
        self.assertEqual(result.latest.version, '10.1')
        self.assertTrue(result.latest.download_url.endswith('.AppImage'))

    def test_bundle_is_preferred_even_if_appimage_is_first_asset(self):
        result = self.fetch([release('10', '2026-10-01T00:00:00Z',
                                     ['wine.AppImage', 'source.tar.gz', 'wine.bundle.tar.xz'])],
                            ('.bundle.tar.xz', '.AppImage'))
        self.assertTrue(result.latest.download_url.endswith('.bundle.tar.xz'))


class TestLauncherReleaseSelection(unittest.TestCase):
    def requests(self):
        from unittest.mock import Mock
        requests = object.__new__(network.NetworkRequests)
        requests._cache = network.CachedRequests()
        requests._cache._write = Mock()
        return requests

    def test_launcher_uses_asset_for_current_architecture(self):
        requests = self.requests()
        data = dict(tag_name='v4.1', assets=[
            dict(name='oudedetai-arm', browser_download_url='https://example.invalid/arm'),
            dict(name='oudedetai-x86_64', browser_download_url='https://example.invalid/x86_64')])
        with patch('ou_dedetai.system.get_architecture', return_value=('x86_64', '')), \
                patch.object(network, '_net_get', return_value=json.dumps(data).encode()):
            result = requests.app_latest_version('stable')
        self.assertEqual(result.download_url, 'https://example.invalid/x86_64')

    def test_launcher_refresh_invalidates_architecture_specific_cache(self):
        requests = self.requests()
        def data(version):
            return json.dumps(dict(tag_name=version, assets=[
                dict(name='oudedetai-x86_64', browser_download_url='https://example.invalid/' + version)
            ])).encode()
        with patch('ou_dedetai.system.get_architecture', return_value=('x86_64', '')), \
                patch.object(network, '_net_get', side_effect=[data('4.1'), data('4.2')]) as fetch:
            self.assertEqual(requests.app_latest_version('stable').version, '4.1')
            self.assertEqual(requests.app_latest_version('stable').version, '4.1')
            self.assertEqual(requests.refresh_app_latest_version('stable').version, '4.2')
        self.assertEqual(fetch.call_count, 2)

    def test_launcher_dev_channel_selects_latest_published_testing_build(self):
        requests = self.requests()
        def build(version, date, draft=False):
            return dict(tag_name=version, published_at=date, prerelease=True, draft=draft,
                        assets=[dict(name='oudedetai-x86_64',
                                     browser_download_url='https://example.invalid/' + version)])
        data = [build('4.3', '2026-11-01T00:00:00Z', draft=True),
                build('4.1', '2026-10-01T00:00:00Z'), build('4.2', '2026-10-20T00:00:00Z')]
        with patch('ou_dedetai.system.get_architecture', return_value=('x86_64', '')), \
                patch.object(network, '_net_get', return_value=json.dumps(data).encode()):
            self.assertEqual(requests.app_latest_version('dev').version, '4.2')
