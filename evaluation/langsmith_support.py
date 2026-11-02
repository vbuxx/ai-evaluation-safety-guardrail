"""Publish live evaluation traces and verify their server-side readback."""

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime
import json
import os
import time
from zoneinfo import ZoneInfo

from langsmith import Client, trace, tracing_context
from langsmith.utils import LangSmithNotFoundError

ACTIVE = ContextVar("langsmith_evaluation", default=None)
DATASET_NAME = "ai-evaluation-safety-guardrail-official-12"
EXPECTED_INTENTS = {
    **dict.fromkeys(["EVAL-01", "EVAL-02", "EVAL-03", "EVAL-10", "EVAL-11"], "faq"),
    **dict.fromkeys(["EVAL-04", "EVAL-05", "EVAL-12"], "unknown"),
    **dict.fromkeys(["EVAL-06", "EVAL-07", "EVAL-08", "EVAL-09"], "ticket_status"),
}


def span(name, run_type="chain", inputs=None, metadata=None, scenario_id=None):
    state = ACTIVE.get()
    if state is None:
        return nullcontext()
    return trace(
        name, run_type=run_type, inputs=inputs, metadata=metadata,
        client=state["client"], project_name=state["project"].name,
        reference_example_id=state["example_ids"].get(scenario_id),
    )


@contextmanager
def session(scenarios, phase, enabled=False):
    if not enabled:
        yield None
        return
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key or api_key == "your_langsmith_api_key_here":
        raise RuntimeError("Isi LANGSMITH_API_KEY di system/.env sebelum memakai --langsmith")
    client = Client(api_key=api_key)
    try:
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    except LangSmithNotFoundError:
        dataset = client.create_dataset(
            DATASET_NAME, description="12 official Assignment 5 scenarios; expected behavior is a reference note, not an exact answer.",
            metadata={"source": "https://docs.google.com/spreadsheets/d/1UvZZlB-hid780MRKKdWimGKUzFy1z2Y_kn9tWVOzAWk/edit"},
        )
    examples = list(client.list_examples(dataset_id=dataset.id))
    existing = {(example.metadata or {}).get("scenario_id"): example for example in examples}
    assert set(existing) <= {row["scenario_id"] for row in scenarios}, "Dataset has unrelated scenarios"
    assert len(existing) == len(examples), "Dataset has duplicate scenario IDs"
    for row in scenarios:
        example = existing.get(row["scenario_id"])
        if example is not None:
            assert example.inputs == {"query": row["query"]}, "Existing dataset query differs from official source"
            assert example.outputs == {"expected_behavior_note": row["expected_behavior_note"]}, "Existing dataset reference differs from official source"
    missing = [row for row in scenarios if row["scenario_id"] not in existing]
    if missing:
        client.create_examples(dataset_id=dataset.id, examples=[
            {"inputs": {"query": row["query"]}, "outputs": {"expected_behavior_note": row["expected_behavior_note"]},
             "metadata": {"scenario_id": row["scenario_id"], "category": row["category"]}}
            for row in missing
        ])
    examples = list(client.list_examples(dataset_id=dataset.id))
    assert len(examples) == len(scenarios), "Dataset examples were not fully saved"
    prefix = os.getenv("LANGSMITH_PROJECT") or "assignment5-helpdesk"
    name = f"{prefix}-{phase}-{datetime.now(ZoneInfo('Asia/Jakarta')):%Y%m%d-%H%M%S}"
    project = client.create_project(
        name, reference_dataset_id=dataset.id, num_examples=len(scenarios),
        metadata={"phase": phase, "transport": "live ASGI + Gemini", "feedback_scope": "routing policy only; not a factual accuracy score"},
    )
    state = {"client": client, "dataset": dataset, "project": project,
             "example_ids": {example.metadata["scenario_id"]: example.id for example in examples}}
    token = ACTIVE.set(state)
    try:
        with tracing_context(enabled=True, client=client, project_name=project.name):
            yield state
    finally:
        ACTIVE.reset(token)


def verify(state, rows):
    """Require completed remote runs and persisted feedback, not upload acknowledgements."""
    client = state["client"]
    client.flush(timeout=15)
    expected_ids = {row["langsmith_run_id"] for row in rows}
    expected_llms = sum(row["generation_calls"] for row in rows)
    expected_embeddings = sum(row["embedding_calls"] for row in rows)
    for attempt in range(6):
        runs = list(client.list_runs(project_id=state["project"].id, limit=200))
        by_id = {str(run.id): run for run in runs}
        if (expected_ids <= by_id.keys() and all(run.end_time is not None for run in runs)
                and sum(run.run_type == "llm" for run in runs) == expected_llms
                and sum(run.run_type == "embedding" for run in runs) == expected_embeddings):
            break
        if attempt == 5:
            raise RuntimeError("LangSmith readback belum memuat seluruh trace yang selesai")
        time.sleep(min(0.5 * 2 ** attempt, 4))
    evidence = []
    for row in rows:
        remote = by_id[row["langsmith_run_id"]]
        assert remote.parent_run_id is None, "Expected a root request trace"
        assert remote.outputs == {"response": json.loads(row["actual_response"])}, "Remote output differs from actual API response"
        score = None
        expected_intent = EXPECTED_INTENTS.get(row["scenario_id"])
        if expected_intent is not None:
            assert remote.reference_example_id == state["example_ids"][row["scenario_id"]]
            score = int(row["intent"] == expected_intent)
            feedback = client.create_feedback(
                remote.id, key="routing_matches_policy", score=score,
                comment=f"Expected intent={expected_intent}; actual={row['intent']}. This checks routing only, not factual correctness.",
            )
            saved = client.read_feedback(feedback.id)
            assert saved.score == score, "Feedback readback differs"
        evidence.append({"scenario_id": row["scenario_id"], "run_id": str(remote.id),
                         "url": client.get_run_url(run=remote), "routing_matches_policy": score})
    project = client.read_project(project_id=str(state["project"].id))
    dataset = client.read_dataset(dataset_id=state["dataset"].id)
    children = [run for run in runs if run.parent_run_id is not None]
    assert children and all(run.end_time is not None for run in children), "Child traces are incomplete"
    return {
        "verified_at": datetime.now(ZoneInfo("Asia/Jakarta")).isoformat(),
        "project_id": str(project.id), "project_name": project.name, "project_url": project.url,
        "dataset_id": str(dataset.id), "dataset_url": dataset.url, "dataset_examples": len(state["example_ids"]),
        "root_runs_verified": len(evidence), "child_runs_verified": len(children),
        "llm_runs_verified": sum(run.run_type == "llm" for run in children),
        "embedding_runs_verified": sum(run.run_type == "embedding" for run in children),
        "routing_feedback_verified": sum(item["routing_matches_policy"] is not None for item in evidence),
        "feedback_scope": "Deterministic routing checks only; content and hallucination remain subject to manual evaluation.",
        "access": "Existing workspace access required; no public sharing was enabled.",
        "runs": evidence,
    }
