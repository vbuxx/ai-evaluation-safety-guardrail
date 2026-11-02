import csv
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from run_evaluation import OUTPUT, TRACE, instrument, interval_ms, rag


class EvaluationTests(unittest.TestCase):
    def test_parallel_provider_time_is_not_double_counted(self):
        calls = [
            {"started_at": 0, "finished_at": 2},
            {"started_at": 1, "finished_at": 3},
            {"started_at": 5, "finished_at": 6},
        ]
        self.assertEqual(interval_ms(calls), 4000)
        self.assertEqual(interval_ms([]), 0)

    def test_all_official_queries_are_preserved(self):
        with (OUTPUT / "sources/evaluation_test_scenarios.csv").open() as f:
            original = list(csv.DictReader(f))
        with (OUTPUT / "evaluation_test_scenarios.csv").open() as f:
            normalized = list(csv.DictReader(f))
        self.assertEqual(len(normalized), 12)
        self.assertEqual(
            [(row["scenario_id"], row["query"]) for row in normalized],
            [(row["scenario_id"], row["query"]) for row in original],
        )

    def test_instrumentation_records_sdk_usage_without_changing_response(self):
        embedding = SimpleNamespace(metadata=SimpleNamespace(billable_character_count=8))
        generation = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=6, candidates_token_count=2,
            thoughts_token_count=0, total_token_count=8,
        ))
        models = SimpleNamespace(
            embed_content=lambda **kwargs: embedding,
            generate_content=lambda **kwargs: generation,
        )
        trace = {"calls": []}
        token = TRACE.set(trace)
        try:
            with patch.object(rag, "_get_client", return_value=SimpleNamespace(models=models)):
                with instrument():
                    actual_embedding = models.embed_content(
                        contents=["test", "data"], config=SimpleNamespace(task_type="RETRIEVAL_QUERY")
                    )
                    actual_generation = models.generate_content(contents="test")
        finally:
            TRACE.reset(token)
        self.assertIs(actual_embedding, embedding)
        self.assertIs(actual_generation, generation)
        self.assertEqual([call["kind"] for call in trace["calls"]], ["embedding", "generation"])
        self.assertEqual(trace["calls"][0]["input_characters"], 8)
        self.assertEqual(trace["calls"][1]["total_token_count"], 8)


if __name__ == "__main__":
    unittest.main()
