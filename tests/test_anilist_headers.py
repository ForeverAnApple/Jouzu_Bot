import unittest
from unittest import mock

from lib.anilist_autocomplete import (
    ANILIST_API_URL,
    ANILIST_HEADERS,
    _post_anilist,
)


class FakeResponse:
    status = 200
    headers = {}

    async def json(self, content_type=None):
        return {"data": {}}


class FakePost:
    """Stands in for the async context manager returned by session.post."""

    def __init__(self, recorder, url, **kwargs):
        recorder["url"] = url
        recorder.update(kwargs)

    async def __aenter__(self):
        return FakeResponse()

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    def __init__(self, recorder):
        self.recorder = recorder

    def post(self, url, **kwargs):
        return FakePost(self.recorder, url, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class TestAnilistHeaders(unittest.IsolatedAsyncioTestCase):
    async def test_post_anilist_identifies_the_bot(self):
        recorder = {}
        with mock.patch(
            "lib.anilist_autocomplete.aiohttp.ClientSession",
            lambda *args, **kwargs: FakeSession(recorder),
        ):
            result = await _post_anilist({"query": "{}"})

        self.assertEqual(result, (200, {"data": {}}, None))
        self.assertEqual(recorder["url"], ANILIST_API_URL)
        self.assertEqual(recorder["headers"], ANILIST_HEADERS)
        self.assertEqual(recorder["json"], {"query": "{}"})


if __name__ == "__main__":
    unittest.main()
