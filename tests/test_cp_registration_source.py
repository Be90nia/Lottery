import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_cp_registration_source import (
    verify_legacy_registration_comment,
    verify_registration_comment,
    verify_solver_parameter_comment,
)


class CpRegistrationSourceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.body = "append-only registration body\nwith exact UTF-8 bytes"
        self.digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        self.registration = {
            "governance_issue_url": "https://github.com/Be90nia/Lottery/issues/27",
            "parent_issue_url": "https://github.com/Be90nia/Lottery/issues/18",
            "child_registration_comment_url": (
                "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7184888699"
            ),
            "child_registration_comment_id": 7184888699,
            "child_registration_comment_sha256": self.digest,
        }
        self.payload = {
            "id": 7184888699,
            "issue_url": "https://api.github.com/repos/Be90nia/Lottery/issues/27",
            "html_url": self.registration["child_registration_comment_url"],
            "user": {"login": "Be90nia"},
            "body": self.body,
        }

    def test_verifies_exact_comment_body_and_repository_lineage(self):
        calls = []

        def fetch_json(url, token):
            calls.append((url, token))
            return self.payload

        actual = verify_registration_comment(
            self.registration, "Be90nia/Lottery", token="test-token", fetch_json=fetch_json,
        )
        self.assertEqual(actual, self.digest)
        self.assertEqual(calls, [(
            "https://api.github.com/repos/Be90nia/Lottery/issues/comments/7184888699",
            "test-token",
        )])

    def test_rejects_comment_body_digest_mismatch(self):
        registration = dict(self.registration)
        registration["child_registration_comment_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "body SHA-256 mismatch"):
            verify_registration_comment(
                registration, "Be90nia/Lottery", token="test-token",
                fetch_json=lambda _url, _token: self.payload,
            )

    def test_rejects_comment_from_another_issue_or_author(self):
        for field, value, message in (
            ("issue_url", "https://api.github.com/repos/Be90nia/Lottery/issues/18", "different issue"),
            ("html_url", "https://github.com/Be90nia/Lottery/issues/18#issuecomment-7184888699", "canonical URL"),
            ("user", {"login": "someone-else"}, "author"),
        ):
            payload = dict(self.payload)
            payload[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, message):
                    verify_registration_comment(
                        self.registration, "Be90nia/Lottery", token="test-token",
                        fetch_json=lambda _url, _token, item=payload: item,
                    )

    def test_rejects_registration_url_and_identifier_mismatch(self):
        registration = dict(self.registration)
        registration["child_registration_comment_id"] = 7184937843
        with self.assertRaisesRegex(ValueError, "URL or issue lineage"):
            verify_registration_comment(
                registration, "Be90nia/Lottery", token="test-token",
                fetch_json=lambda _url, _token: self.payload,
            )


    def test_rejects_wrong_parent_protocol_lineage_before_api_access(self):
        registration = dict(self.registration)
        registration["parent_issue_url"] = "https://github.com/Be90nia/Lottery/issues/19"

        def unexpected_fetch(*_args):
            self.fail("API must not be called for mismatched parent protocol lineage")

        with self.assertRaisesRegex(ValueError, "parent LOT-055 protocol"):
            verify_registration_comment(
                registration, "Be90nia/Lottery", token="test-token", fetch_json=unexpected_fetch,
            )

    def test_verifies_legacy_g3_child_registration_comment(self):
        registration = {
            "legacy_parent_issue_url": "https://github.com/Be90nia/Lottery/issues/18",
            "legacy_child_registration_comment_url": (
                "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7028060751"
            ),
            "legacy_child_registration_comment_sha256": self.digest,
        }
        payload = {
            "id": 7028060751,
            "issue_url": "https://api.github.com/repos/Be90nia/Lottery/issues/27",
            "html_url": registration["legacy_child_registration_comment_url"],
            "user": {"login": "Be90nia"},
            "body": self.body,
        }
        actual = verify_legacy_registration_comment(
            registration, "Be90nia/Lottery", token="test-token",
            fetch_json=lambda _url, _token: payload,
        )
        self.assertEqual(actual, self.digest)

    def test_rejects_legacy_comment_digest_mismatch(self):
        registration = {
            "legacy_parent_issue_url": "https://github.com/Be90nia/Lottery/issues/18",
            "legacy_child_registration_comment_url": (
                "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7028060751"
            ),
            "legacy_child_registration_comment_sha256": "0" * 64,
        }
        payload = {
            "id": 7028060751,
            "issue_url": "https://api.github.com/repos/Be90nia/Lottery/issues/27",
            "html_url": registration["legacy_child_registration_comment_url"],
            "user": {"login": "Be90nia"},
            "body": self.body,
        }
        with self.assertRaisesRegex(ValueError, "body SHA-256 mismatch"):
            verify_legacy_registration_comment(
                registration, "Be90nia/Lottery", token="test-token",
                fetch_json=lambda _url, _token: payload,
            )

    def test_rejects_invalid_digest_before_api_access(self):
        registration = dict(self.registration)
        registration["child_registration_comment_sha256"] = "not-a-digest"

        def unexpected_fetch(*_args):
            self.fail("API must not be called for malformed registration")

        with self.assertRaisesRegex(ValueError, "missing or malformed"):
            verify_registration_comment(
                registration, "Be90nia/Lottery", token="test-token", fetch_json=unexpected_fetch,
            )


    def test_verifies_solver_parameter_comment_digest_and_identity(self):
        body = (
            "## Registration parameter clarification — exact Strong-Wolfe constants\\n\\n"
            "For the registered child `LOT055-CP-CALIBRATION-DIAG-20261126`, the reviewed implementation at "
            "`e7be74402188218603ff07cf745772380947800a` fixes the line-search settings as:\\n"
            "- Armijo constant `c1 = 1e-4`;\\n"
            "- curvature constant `c2 = 0.9`;\\n"
            "- line-search/zoom iteration bound `60`;\\n"
            "- initial trial step `1.0`, doubling on the bracketing phase;\\n"
            "- deterministic midpoint bisection in zoom.\\n\\n"
            "These are fixed implementation parameters, not a search space. Record them explicitly in the child trial plan and per-artifact calibration configuration. No tuning of these constants is permitted under this child."
        )
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        registration = {
            "parent_issue_url": "https://github.com/Be90nia/Lottery/issues/18",
            "solver_parameter_comment_url": (
                "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7184937843"
            ),
            "solver_parameter_comment_id": 7184937843,
            "solver_parameter_comment_sha256": digest,
        }
        payload = {
            "id": 7184937843,
            "issue_url": "https://api.github.com/repos/Be90nia/Lottery/issues/27",
            "html_url": registration["solver_parameter_comment_url"],
            "user": {"login": "Be90nia"},
            "body": body,
        }
        calls = []
        actual = verify_solver_parameter_comment(
            registration, "Be90nia/Lottery", digest_expected=digest,
            token="test-token",
            fetch_json=lambda url, token: calls.append((url, token)) or payload,
        )
        self.assertEqual(actual, digest)
        self.assertEqual(calls, [(
            "https://api.github.com/repos/Be90nia/Lottery/issues/comments/7184937843",
            "test-token",
        )])

    def test_requires_solver_parameter_digest_in_immutable_registration(self):
        registration = {
            "parent_issue_url": "https://github.com/Be90nia/Lottery/issues/18",
            "solver_parameter_comment_url": (
                "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7184937843"
            ),
            "solver_parameter_comment_id": 7184937843,
        }
        with self.assertRaisesRegex(ValueError, "must pin solver_parameter_comment_sha256"):
            verify_solver_parameter_comment(
                registration, "Be90nia/Lottery", digest_expected="0" * 64,
                token="test-token", fetch_json=lambda _url, _token: {},
            )

    def test_rejects_solver_parameter_comment_digest_or_identity_mismatch(self):
        registration = {
            "solver_parameter_comment_url": (
                "https://github.com/Be90nia/Lottery/issues/27#issuecomment-7184937843"
            ),
            "solver_parameter_comment_id": 7184937843,
            "solver_parameter_comment_sha256": "0" * 64,
        }
        payload = {
            "id": 7184937843,
            "issue_url": "https://api.github.com/repos/Be90nia/Lottery/issues/27",
            "html_url": registration["solver_parameter_comment_url"],
            "user": {"login": "Be90nia"},
            "body": "fixed solver settings",
        }
        with self.assertRaisesRegex(ValueError, "body SHA-256 mismatch"):
            verify_solver_parameter_comment(
                registration, "Be90nia/Lottery", digest_expected="0" * 64,
                token="test-token", fetch_json=lambda _url, _token: payload,
            )
        registration["solver_parameter_comment_id"] = 7184888699
        with self.assertRaisesRegex(ValueError, "not the registered clarification"):
            verify_solver_parameter_comment(
                registration, "Be90nia/Lottery", digest_expected="0" * 64,
                token="test-token", fetch_json=lambda _url, _token: payload,
            )



if __name__ == "__main__":
    unittest.main()
