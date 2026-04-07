from __future__ import annotations

import os
from io import BytesIO

from flask import current_app
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.colors import black, white
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


CARD_WIDTH = 90 * mm
CARD_HEIGHT = 55 * mm
MARGIN = 3 * mm


def _fit_text(
    pdf: canvas.Canvas,
    text: str,
    max_width: float,
    font_name: str,
    max_size: int,
    min_size: int,
) -> int:
    size = max_size
    while size >= min_size:
        if pdf.stringWidth(text, font_name, size) <= max_width:
            return size
        size -= 1
    return min_size


def build_mechanic_badge_pdf(mechanic) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(CARD_WIDTH, CARD_HEIGHT))

    mechanic_name = (getattr(mechanic, "name", "") or "").strip() or "SIN NOMBRE"
    mechanic_code = (getattr(mechanic, "code", "") or "").strip() or "SIN CÓDIGO"

    # =========================
    # FONDO Y BORDE
    # =========================
    pdf.setFillColor(white)
    pdf.rect(0, 0, CARD_WIDTH, CARD_HEIGHT, fill=1, stroke=0)

    pdf.setStrokeColor(black)
    pdf.setLineWidth(1)
    pdf.rect(
        MARGIN,
        MARGIN,
        CARD_WIDTH - (MARGIN * 2),
        CARD_HEIGHT - (MARGIN * 2),
        fill=0,
        stroke=1,
    )

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join(
        current_app.root_path,
        "static",
        "img",
        "logo.png",
    )

    logo_bottom_y = CARD_HEIGHT - 12 * mm
    logo_width = 24 * mm
    logo_height = 10 * mm

    if os.path.exists(logo_path):
        try:
            logo = ImageReader(logo_path)
            pdf.drawImage(
                logo,
                (CARD_WIDTH - logo_width) / 2,
                logo_bottom_y,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    # =========================
    # NOMBRE
    # =========================
    name_y = CARD_HEIGHT - 17 * mm
    name_font_size = _fit_text(
        pdf=pdf,
        text=mechanic_name,
        max_width=CARD_WIDTH - 16 * mm,
        font_name="Helvetica-Bold",
        max_size=12,
        min_size=8,
    )

    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", name_font_size)
    pdf.drawCentredString(CARD_WIDTH / 2, name_y, mechanic_name)

    # =========================
    # BARCODE
    # =========================
    barcode = createBarcodeDrawing(
        "Code128",
        value=mechanic_code,
        barHeight=11 * mm,
        barWidth=0.40 * mm,
        humanReadable=False,
    )

    barcode_x = (CARD_WIDTH - barcode.width) / 2
    barcode_y = 18 * mm
    renderPDF.draw(barcode, pdf, barcode_x, barcode_y)

    # =========================
    # CÓDIGO ALFANUMÉRICO
    # =========================
    pdf.setFillColor(black)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(CARD_WIDTH / 2, 13 * mm, mechanic_code)

    pdf.showPage()
    pdf.save()

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes