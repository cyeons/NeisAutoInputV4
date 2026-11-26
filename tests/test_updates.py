from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from neis_v4.updates import LATEST_RELEASE_API, RELEASES_PAGE, fetch_latest_release, is_newer


class UpdateCheckTests(unittest.TestCase):
    def test_only_higher_versions_count_as_new(self) -> None:
        self.assertTrue(is_newer("v4.6.0", "4.5.0"))
        self.assertTrue(is_newer("v4.10.0", "4.9.1"))  # 글자 비교가 아니라 숫자 비교
        self.assertFalse(is_newer("v4.5.0", "4.5.0"))
        self.assertFalse(is_newer("v4.3.0", "4.5.0"))
        self.assertFalse(is_newer("", "4.5.0"))

    def test_latest_release_tag_and_page_are_read(self) -> None:
        reply = {"tag_name": "v4.6.0", "html_url": "https://github.com/cyeons/NeisAutoInputV4/releases/tag/v4.6.0"}
        with patch(
            "neis_v4.updates.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(reply).encode("utf-8")),
        ) as urlopen:
            self.assertEqual(fetch_latest_release(), ("v4.6.0", reply["html_url"]))
        self.assertEqual(urlopen.call_args.args[0].full_url, LATEST_RELEASE_API)

    def test_non_github_page_is_not_opened(self) -> None:
        reply = {"tag_name": "v4.6.0", "html_url": "https://example.com/fake"}
        with patch(
            "neis_v4.updates.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(reply).encode("utf-8")),
        ):
            self.assertEqual(fetch_latest_release(), ("v4.6.0", RELEASES_PAGE))


if __name__ == "__main__":
    unittest.main()
