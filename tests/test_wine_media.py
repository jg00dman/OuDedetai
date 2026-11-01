import unittest
from unittest import mock

from ou_dedetai import wine


class TestMediaPlaybackSetup(unittest.TestCase):
    def test_configure_media_playback_enables_ffmpeg_source(self):
        app = mock.Mock()
        with mock.patch.object(wine, "wine_reg_install") as install:
            wine.configure_media_playback(app, "/fake/wine64")

        reg_text = install.call_args.args[2]
        self.assertTrue(reg_text.startswith("REGEDIT4"))
        self.assertIn("[HKEY_CURRENT_USER\\Software\\Wine\\MediaFoundation]", reg_text)
        self.assertIn('"DisableGstByteStreamHandler"=dword:00000001', reg_text)

    def _ensure_renderer(self, current):
        app = mock.Mock()
        with mock.patch.object(wine, "wine_reg_query", return_value=current) as query, \
                mock.patch.object(wine, "set_renderer") as set_renderer:
            wine.ensure_media_renderer(app, "/fake/wine64")
        query.assert_called_once_with(app, "HKEY_CURRENT_USER\\Software\\Wine\\Direct3D", "renderer")
        return set_renderer

    def test_old_gdi_default_moves_to_gl(self):
        set_renderer = self._ensure_renderer("gdi")
        set_renderer.assert_called_once_with(mock.ANY, "/fake/wine64", "gl")

    def test_unset_renderer_moves_to_gl(self):
        set_renderer = self._ensure_renderer(None)
        set_renderer.assert_called_once_with(mock.ANY, "/fake/wine64", "gl")

    def test_unknown_dxvk_value_moves_to_gl(self):
        set_renderer = self._ensure_renderer("dxvk")
        set_renderer.assert_called_once_with(mock.ANY, "/fake/wine64", "gl")

    def test_user_chosen_vulkan_is_kept(self):
        set_renderer = self._ensure_renderer("vulkan")
        set_renderer.assert_not_called()

    def test_gl_is_kept(self):
        set_renderer = self._ensure_renderer("gl")
        set_renderer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
