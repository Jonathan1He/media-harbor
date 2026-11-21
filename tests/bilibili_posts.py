"""Check Bilibili part selection, advertised qualities and preview handling offline."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import meta, options, rows
from yt_dlp import YoutubeDL


class BilibiliPostTest(unittest.TestCase):
    def setUp(self):
        page = "https://www.bilibili.com/video/BV15BSdBBELf/?p=2"
        self.req = dict(source=page, page=page, kind="page", name="test video")
        self.ydl = self.enterContext(YoutubeDL(options(self.req)))
        self.enterContext(patch.object(self.ydl, "urlopen", self.response))
        self.preview = False
        self.requested_cids = []

    def response(self, request):
        endpoint = urlsplit(request.url)
        if endpoint.path == "/x/player/pagelist":
            data = [dict(page=i, cid=i*10, part=f"part {i}") for i in (1, 2)]
        elif endpoint.path == "/x/player/playurl":
            self.requested_cids.append(parse_qs(endpoint.query)["cid"][0])
            video = dict(id=32, baseUrl="https://media.example/video", height=480, width=852,
                         mimeType="video/mp4", codecs="avc1", frameRate="30")
            data = dict(quality=80, accept_quality=[80, 32], is_preview=self.preview,
                        dash={"audio": [], "video": [video]})
        elif endpoint.path == "/x/web-interface/view":
            return io.BytesIO(b'{"code":-1,"message":"unavailable"}')
        else:
            self.fail(endpoint.path)
        return io.BytesIO(json.dumps({"code": 0, "data": data}).encode())

    def test_actual_tracks_and_part_when_title_is_unavailable(self):
        info = meta(self.ydl, self.req)
        self.assertEqual(self.requested_cids, ["20"])
        self.assertEqual(info["title"], "test video · P2 part 2")
        self.assertEqual([f["height"] for f in rows(info)], [480])

    def test_missing_part_does_not_download_first_part(self):
        self.req["source"] = self.req["source"].replace("p=2", "p=3")
        with self.assertRaisesRegex(ValueError, "第 3 P"):
            meta(self.ydl, self.req)
        self.assertFalse(self.requested_cids)

    def test_preview_is_not_offered_as_complete(self):
        self.preview = True
        with self.assertRaisesRegex(ValueError, "完整视频"):
            meta(self.ydl, self.req)


if __name__ == "__main__":
    unittest.main()
