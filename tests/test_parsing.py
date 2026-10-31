import unittest

from dyxhs import xhs
from dyxhs.common import detect_platform, sanitize
from dyxhs.douyin import _video_id_from_url


class XhsParsingTest(unittest.TestCase):
    def test_extract_state_handles_undefined(self):
        html = '<script>window.__INITIAL_STATE__={"a":undefined,"b":1}</script>'
        self.assertEqual(xhs._extract_state(html), {"a": None, "b": 1})

    def test_video_prefers_higher_resolution(self):
        note = {
            "noteId": "n1",
            "type": "video",
            "title": "t",
            "video": {
                "media": {
                    "stream": {
                        "h264": [{"masterUrl": "h264-url", "width": 1080, "height": 1920}],
                        "h265": [{"masterUrl": "h265-url", "width": 2160, "height": 3840}],
                    }
                }
            },
        }
        self.assertEqual(xhs._best_video(note), ("h265", "h265-url"))

    def test_video_prefers_h264_on_tie(self):
        note = {
            "noteId": "n1",
            "type": "video",
            "title": "t",
            "video": {
                "media": {
                    "stream": {
                        "h264": [{"masterUrl": "h264-url", "width": 1080, "height": 1920}],
                        "h265": [{"masterUrl": "h265-url", "width": 1080, "height": 1920}],
                    }
                }
            },
        }
        self.assertEqual(xhs._best_video(note), ("h264", "h264-url"))

    def test_pick_note_mobile_layout(self):
        state = {"noteData": {"data": {"noteData": {"noteId": "n2", "type": "video"}}}}
        self.assertEqual(xhs._pick_note(state, "n2")["noteId"], "n2")

    def test_image_urls_fall_back_to_info_list(self):
        note = {
            "imageList": [
                {"urlDefault": "default-url"},
                {"infoList": [{"imageScene": "WB_DFT", "url": "dft-url"}]},
            ]
        }
        self.assertEqual(xhs._image_urls(note), ["default-url", "dft-url"])


class CommonTest(unittest.TestCase):
    def test_detect_platform(self):
        self.assertEqual(detect_platform("复制打开抖音 https://v.douyin.com/abc/"), "douyin")
        self.assertEqual(detect_platform("https://xhslink.com/a/b"), "xhs")
        self.assertIsNone(detect_platform("https://example.com/video/1"))

    def test_sanitize_windows_chars(self):
        cleaned = sanitize('a/b:c*?"<>|d')
        self.assertTrue(cleaned.startswith("a_b_c"))
        self.assertFalse(any(ch in cleaned for ch in '\\/:*?"<>|'))

    def test_douyin_video_id(self):
        self.assertEqual(_video_id_from_url("https://www.douyin.com/video/7605270259202168933"), "7605270259202168933")


if __name__ == "__main__":
    unittest.main()
