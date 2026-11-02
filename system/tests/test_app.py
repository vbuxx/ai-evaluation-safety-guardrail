import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd

from app import rag
from app.main import AskRequest, ask
from app.router import detect_intent, extract_ticket_id, handle_query
from app.tools import get_ticket_status


class HelpdeskTests(unittest.TestCase):
    def test_detect_intent(self):
        self.assertEqual(asyncio.run(detect_intent("Berapa jatah cuti?")), "faq")
        self.assertEqual(asyncio.run(detect_intent("Cek TICKET-0001")), "ticket_status")
        self.assertEqual(asyncio.run(detect_intent("Siapa presiden sekarang?")), "unknown")

    def test_all_knowledge_base_questions_route_to_faq(self):
        rows = pd.read_csv(rag.KNOWLEDGE_BASE_PATH, dtype=str)
        for query in rows["question"]:
            with self.subTest(query=query):
                self.assertEqual(asyncio.run(detect_intent(query)), "faq")

    def test_semantic_search_builds_index_and_returns_best_match(self):
        rows = pd.read_csv(rag.KNOWLEDGE_BASE_PATH, dtype=str)
        target = rows[rows["faq_id"] == "29"].iloc[0]
        vectors = np.tile([1, 0], (len(rows), 1)).astype("float32")
        vectors[target.name] = [0, 1]
        query = "komunikasi internal"

        with patch.multiple(rag, _index=None, _documents=None, _df=None), patch.object(
            rag, "_get_embeddings",
            side_effect=[vectors, np.array([[0, 1]], dtype="float32")],
        ) as embeddings:
            results = rag.semantic_search(query, top_k=1)
            self.assertEqual(rag._index.ntotal, len(rows))

        self.assertEqual(results, [{
            "category": target["category"],
            "question": target["question"],
            "answer": target["answer"],
            "score": 1.0,
        }])
        self.assertEqual(embeddings.call_args_list[0].args[1], "RETRIEVAL_DOCUMENT")
        embeddings.assert_called_with([query], "RETRIEVAL_QUERY")

    def test_extract_ticket_id(self):
        self.assertEqual(extract_ticket_id("cek ticket-0015 dong"), "TICKET-0015")
        self.assertIsNone(extract_ticket_id("cek tiket saya"))

    def test_ticket_tool_found_and_not_found(self):
        self.assertIn("Status: Selesai", get_ticket_status("TICKET-0001"))
        self.assertEqual(
            get_ticket_status("TICKET-9999"),
            "Tiket TICKET-9999 tidak ditemukan.",
        )

    def test_ticket_route_without_id(self):
        result = asyncio.run(handle_query("Tolong cek status tiket saya"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["intent"], "ticket_status")

    def test_faq_endpoint_response(self):
        with patch(
            "app.router.answer_from_knowledge_base",
            new=AsyncMock(return_value="Karyawan tetap mendapat 12 hari cuti."),
        ):
            result = asyncio.run(ask(AskRequest(query="Berapa jatah cuti?")))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.intent, "faq")


if __name__ == "__main__":
    unittest.main()
