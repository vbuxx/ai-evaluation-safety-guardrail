"""Tool untuk mengambil data tiket helpdesk."""

from pathlib import Path

import pandas as pd

MOCK_TICKETS_PATH = Path(__file__).resolve().parent.parent / "data" / "mock_tickets.csv"


def get_ticket_status(ticket_id: str) -> str:
    """Mengembalikan ringkasan tiket atau pesan jika tiket tidak ditemukan."""
    if not ticket_id:
        return "ID tiket belum diberikan. Gunakan format TICKET-XXXX."

    tickets = pd.read_csv(MOCK_TICKETS_PATH, dtype=str)
    match = tickets[tickets["ticket_id"].str.upper() == ticket_id.upper()]
    if match.empty:
        return f"Tiket {ticket_id.upper()} tidak ditemukan."

    ticket = match.iloc[0]
    return (
        f"{ticket['ticket_id']} — {ticket['subject']}. "
        f"Status: {ticket['status']}. Terakhir diperbarui: {ticket['last_update']}."
    )
