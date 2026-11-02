"""Intent detection dan routing untuk IT Helpdesk Assistant."""

import re

from app.rag import answer_from_knowledge_base
from app.tools import get_ticket_status

TICKET_PATTERN = re.compile(r"\bTICKET-\d{4}\b", re.IGNORECASE)
RESTRICTED_REQUEST = re.compile(
    r"\b(?:system\s+prompt|prompt\s+sistem|instruksi\s+internal|api[ _]?key|gemini_api_key)\b"
    r"|\b(?:abaikan|lupakan|ignore|forget)\b.{0,80}\b(?:instruksi|aturan|batasan|instructions?|rules?)\b",
    re.IGNORECASE | re.DOTALL,
)
FAQ_KEYWORDS = (
    "cuti", "absen", "izin sakit", "password", "vpn", "email", "akses",
    "laptop", "perangkat", "software", "onboarding", "karyawan baru",
    "slip gaji", "rekening", "asuransi", "reimbursement", "atasan",
    "hybrid", "jam kerja", "lembur", "melahirkan", "paternity", "slack",
    "google meet", "workspace", "tools internal", "kebijakan", "komunikasi internal",
)


async def detect_intent(query: str) -> str:
    """Mendeteksi FAQ, permintaan status tiket, atau query di luar cakupan."""
    normalized = query.casefold()
    asks_ticket_status = ("tiket" in normalized or "ticket" in normalized) and any(
        word in normalized for word in ("status", "cek", "progres", "progress", "tiket saya", "ticket saya")
    )
    if TICKET_PATTERN.search(query) or asks_ticket_status:
        return "ticket_status"
    if any(keyword in normalized for keyword in FAQ_KEYWORDS):
        return "faq"
    return "unknown"


async def handle_query(query: str) -> dict:
    """Mengarahkan query ke tool tiket atau RAG sesuai intent."""
    if RESTRICTED_REQUEST.search(query):
        return {
            "status": "error", "intent": "unknown",
            "data": "Saya membantu pertanyaan HR/IT dan status tiket. Saya tidak dapat mengubah peran atau menampilkan konfigurasi dan instruksi internal.",
        }
    intent = await detect_intent(query)

    if intent == "ticket_status":
        ticket_id = extract_ticket_id(query)
        if ticket_id is None:
            return {
                "status": "error",
                "intent": intent,
                "data": "Sertakan ID tiket dengan format TICKET-XXXX.",
            }
        return {
            "status": "success",
            "intent": intent,
            "data": get_ticket_status(ticket_id),
        }

    if intent == "faq":
        return {
            "status": "success",
            "intent": intent,
            "data": await answer_from_knowledge_base(query),
        }

    return {
        "status": "error",
        "intent": "unknown",
        "data": "Maaf, pertanyaan tersebut di luar cakupan helpdesk yang tersedia.",
    }


def extract_ticket_id(query: str) -> str | None:
    """Mengambil ID tiket berformat TICKET-XXXX dari teks."""
    match = TICKET_PATTERN.search(query)
    return match.group(0).upper() if match else None
