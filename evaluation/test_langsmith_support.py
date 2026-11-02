import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

import langsmith_support as support
from run_evaluation import app, measure


class LangSmithTests(unittest.TestCase):
    def test_disabled_mode_never_creates_a_client(self):
        with patch.object(support, "Client") as client:
            with support.session([], "after") as state:
                self.assertIsNone(state)
                with support.span("test") as remote:
                    self.assertIsNone(remote)
        client.assert_not_called()

    def test_missing_key_fails_before_remote_writes(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "", "LANGCHAIN_API_KEY": ""}), patch.object(support, "Client") as client:
            with self.assertRaisesRegex(RuntimeError, "LANGSMITH_API_KEY"):
                with support.session([], "after", enabled=True):
                    pass
        client.assert_not_called()

    def test_existing_dataset_with_different_query_is_not_overwritten(self):
        client = Mock()
        client.read_dataset.return_value = SimpleNamespace(id=uuid4())
        client.list_examples.return_value = [SimpleNamespace(
            metadata={"scenario_id": "EVAL-01"}, inputs={"query": "different query"}, outputs={},
        )]
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-only"}), patch.object(support, "Client", return_value=client):
            with self.assertRaisesRegex(AssertionError, "query differs"):
                with support.session([{"scenario_id": "EVAL-01", "query": "official query"}], "after", enabled=True):
                    pass
        client.create_examples.assert_not_called()
        client.create_project.assert_not_called()

    def test_request_trace_contains_actual_response_and_numeric_metrics(self):
        remote = Mock(id=uuid4())

        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await measure(client, "SAFE-03", "Scope", "Siapa pemenang sepak bola?")

        with patch("run_evaluation.cloud_span", return_value=nullcontext(remote)):
            row, trace = asyncio.run(request())
        self.assertEqual(row["langsmith_run_id"], str(remote.id))
        self.assertEqual(remote.end.call_args.kwargs["outputs"], {"response": json.loads(row["actual_response"])})
        self.assertTrue(all(isinstance(value, (int, float)) for value in remote.end.call_args.kwargs["metadata"]["metrics"].values()))

    def test_incomplete_readback_cannot_be_reported_as_verified(self):
        client = Mock()
        client.list_runs.return_value = []
        row = {"langsmith_run_id": str(uuid4()), "generation_calls": 0, "embedding_calls": 0}
        with patch.object(support.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "readback"):
                support.verify({"client": client, "project": SimpleNamespace(id=uuid4())}, [row])
        client.create_feedback.assert_not_called()

    def test_routing_failure_is_saved_as_zero_feedback(self):
        client = Mock()
        example_id, run_id = uuid4(), uuid4()
        body = {"status": "error", "intent": "unknown", "data": "Di luar cakupan"}
        root = SimpleNamespace(id=run_id, parent_run_id=None, end_time=datetime.now(timezone.utc),
                               run_type="chain", outputs={"response": body}, reference_example_id=example_id)
        child = SimpleNamespace(id=uuid4(), parent_run_id=run_id, end_time=datetime.now(timezone.utc), run_type="llm")
        client.list_runs.return_value = [root, child]
        client.read_feedback.return_value = SimpleNamespace(score=0)
        client.read_project.return_value = SimpleNamespace(id=uuid4(), name="test", url="https://smith.langchain.com/test-project")
        client.read_dataset.return_value = SimpleNamespace(id=uuid4(), url="https://smith.langchain.com/test-dataset")
        state = {"client": client, "project": SimpleNamespace(id=uuid4()), "dataset": SimpleNamespace(id=uuid4()),
                 "example_ids": {"EVAL-01": example_id}}
        row = {"scenario_id": "EVAL-01", "intent": "unknown", "langsmith_run_id": str(run_id),
               "actual_response": json.dumps(body), "generation_calls": 1, "embedding_calls": 0}
        result = support.verify(state, [row])
        self.assertEqual(client.create_feedback.call_args.kwargs["score"], 0)
        self.assertEqual(result["routing_feedback_verified"], 1)
        self.assertEqual(result["runs"][0]["routing_matches_policy"], 0)


if __name__ == "__main__":
    unittest.main()
