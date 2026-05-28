from datetime import datetime, UTC

from app.extensions import db
from app.models.transfer_document import TransferDocument
from app.services.transfer_pdf_service import generate_transfer_pdf


def generate_and_store_transfer_pdf(
    transfer,
    generated_by_user_id: int | None = None,
):
    existing = (
        TransferDocument.query
        .filter(
            TransferDocument.transfer_id == transfer.id,
            TransferDocument.document_type == "TRANSFER_PDF",
        )
        .first()
    )

    if existing:
        return existing

    pdf_buffer = generate_transfer_pdf(transfer)
    pdf_data = pdf_buffer.getvalue()

    document = TransferDocument(
        transfer_id=transfer.id,
        document_type="TRANSFER_PDF",
        filename=f"traslado_{transfer.number}.pdf",
        mime_type="application/pdf",
        file_data=pdf_data,
        generated_by_user_id=generated_by_user_id,
        generated_at=datetime.now(UTC),
    )

    db.session.add(document)
    db.session.flush()

    return document