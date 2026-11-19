import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lottery.ingest import IngestionError, _RejectRedirect, _fetch_page


class RedirectPolicyTests(unittest.TestCase):
    def test_redirect_handler_rejects_before_following_location(self):
        request = urllib.request.Request(
            "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
        )
        handler = _RejectRedirect()
        with self.assertRaisesRegex(IngestionError, "refusing HTTP redirect"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {"Location": "https://example.invalid/redirect-target"},
                "https://example.invalid/redirect-target",
            )

    def test_fetch_page_fails_immediately_on_http_redirect(self):
        class RedirectingOpener:
            calls = 0

            def open(self, request, timeout):
                self.calls += 1
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "https://example.invalid/redirect-target"},
                    None,
                )

        opener = RedirectingOpener()
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(IngestionError, "HTTP redirect rejected"):
                _fetch_page(1, 100, retries=3)
        self.assertEqual(opener.calls, 1)

    def test_fetch_page_rejects_unexpected_final_url(self):
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://example.invalid/redirect-target"

            def read(self):
                return b"{}"

        class Opener:
            def open(self, request, timeout):
                return Response()

        with patch("urllib.request.build_opener", return_value=Opener()):
            with self.assertRaisesRegex(IngestionError, "response URL differs"):
                _fetch_page(1, 100, retries=1)


if __name__ == "__main__":
    unittest.main()
