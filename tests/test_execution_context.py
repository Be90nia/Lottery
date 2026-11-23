import unittest

from lottery.execution_context import (
    EXECUTION_SCHEMA,
    ExecutionContextError,
    execution_context_from_env,
    validate_execution_context,
)


REPOSITORY = "Be90nia/Lottery"
REPOSITORY_ID = "1461523125"
WORKFLOW_PATH = ".github/workflows/subset-research.yml"
COMMIT = "a" * 40


def environment(*, run_id="45130000000", attempt="1", sha=COMMIT):
    return {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{WORKFLOW_PATH}@refs/heads/feature",
        "GITHUB_RUN_ID": run_id,
        "GITHUB_RUN_ATTEMPT": attempt,
        "GITHUB_JOB": "run-evaluation",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/feature",
        "GITHUB_SHA": sha,
        "GITHUB_ACTOR": "research-operator",
    }


class ExecutionContextTests(unittest.TestCase):
    def make_context(self, **kwargs):
        return execution_context_from_env(
            environment(**kwargs),
            checked_out_sha=kwargs.get("sha", COMMIT),
            expected_repository=REPOSITORY,
            expected_repository_id=REPOSITORY_ID,
            expected_workflow_path=WORKFLOW_PATH,
        )

    def test_context_binds_actual_workflow_run_and_attempt(self):
        context = self.make_context()
        self.assertEqual(context["schema"], EXECUTION_SCHEMA)
        self.assertEqual(context["workflow_path"], WORKFLOW_PATH)
        self.assertEqual(context["run_id"], 45130000000)
        self.assertEqual(context["run_attempt"], 1)
        self.assertEqual(len(context["execution_id"]), 64)
        self.assertEqual(
            validate_execution_context(
                context,
                expected_repository=REPOSITORY,
                expected_repository_id=REPOSITORY_ID,
                expected_workflow_path=WORKFLOW_PATH,
            ),
            context,
        )

    def test_rerun_attempt_has_distinct_execution_identity(self):
        first = self.make_context(run_id="45130000000", attempt="1")
        rerun = self.make_context(run_id="45130000000", attempt="2")
        independent = self.make_context(run_id="45130000001", attempt="1")
        self.assertNotEqual(first["execution_id"], rerun["execution_id"])
        self.assertNotEqual(first["execution_id"], independent["execution_id"])

    def test_wrong_repository_workflow_or_checked_out_sha_is_rejected(self):
        wrong_repo = environment()
        wrong_repo["GITHUB_REPOSITORY"] = "someone/else"
        with self.assertRaisesRegex(ExecutionContextError, "repository"):
            execution_context_from_env(
                wrong_repo, checked_out_sha=COMMIT,
                expected_repository=REPOSITORY, expected_repository_id=REPOSITORY_ID,
                expected_workflow_path=WORKFLOW_PATH,
            )
        wrong_workflow = environment()
        wrong_workflow["GITHUB_WORKFLOW_REF"] = f"{REPOSITORY}/.github/workflows/other.yml@refs/heads/feature"
        with self.assertRaisesRegex(ExecutionContextError, "workflow path"):
            execution_context_from_env(
                wrong_workflow, checked_out_sha=COMMIT,
                expected_repository=REPOSITORY, expected_repository_id=REPOSITORY_ID,
                expected_workflow_path=WORKFLOW_PATH,
            )
        with self.assertRaisesRegex(ExecutionContextError, "does not match GITHUB_SHA"):
            execution_context_from_env(
                environment(), checked_out_sha="b" * 40,
                expected_repository=REPOSITORY, expected_repository_id=REPOSITORY_ID,
                expected_workflow_path=WORKFLOW_PATH,
            )

    def test_tampered_execution_id_and_extra_fields_are_rejected(self):
        context = self.make_context()
        context["execution_id"] = "0" * 64
        with self.assertRaisesRegex(ExecutionContextError, "execution_id"):
            validate_execution_context(
                context,
                expected_repository=REPOSITORY,
                expected_repository_id=REPOSITORY_ID,
                expected_workflow_path=WORKFLOW_PATH,
            )
        context = self.make_context()
        context["untrusted_extra"] = True
        with self.assertRaisesRegex(ExecutionContextError, "closed schema"):
            validate_execution_context(
                context,
                expected_repository=REPOSITORY,
                expected_repository_id=REPOSITORY_ID,
                expected_workflow_path=WORKFLOW_PATH,
            )


if __name__ == "__main__":
    unittest.main()
