from __future__ import annotations

from io import BytesIO
import os

from flask import current_app
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.colors import black, white
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


def _fit_text(pdf: canvas.Canvas, text: str, max_width: float, font_name: str, max_size: int, min_size: int) -> int:
    size = max_size
    while size >= min_size:
        if pdf.stringWidth(text, font_name, size) <= max_width:
            return size
        size -= 1
    return min_size


def build_mechanic_badge_pdf(mechanic) -> bytes:
    buffer = BytesIO()

    width = 90 * mm
    height = 55 * mm

    pdf = canvas.Canvas(buffer, pagesize=(width, height))

    # Fondo
    pdf.setFillColor(white)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)

    # Borde
    pdf.setStrokeColor(black)
    pdf.setLineWidth(1)
    pdf.rect(3 * mm, 3 * mm, width - 6 * mm, height - 6 * mm, fill=0, stroke=1)

    mechanic_name = (getattr(mechanic, "name", "") or "").strip()
    mechanic_code = (getattr(mechanic, "code", "") or "").strip()

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join(
        current_app.root_path,
        "static",
        "img",
        "logo.png"
    )

    if os.path.exists(logo_path):
        try:
            logo = ImageReader(logo_path)

            logo_width = 24 * mm
            logo_height = 12 * mm

            pdf.drawImage(
                logo,
                (width - logo_width) / 2,
                height - 14 * mm,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask='auto'
            )
        except Exception:
            pass

    # =========================
    # NOMBRE (AJUSTADO)
    # =========================
    name_font_size = _fit_text(
        pdf,
        mechanic_name or "SIN NOMBRE",
        width - 16 * mm,
        "Helvetica-Bold",
        12,
        8,
    )

    pdf.setFont("Helvetica-Bold", name_font_size)
    pdf.drawCentredString(
        width / 2,
        height - 20 * mm,   # 🔥 AJUSTE CLAVE (antes estaba muy arriba)
        mechanic_name or "SIN NOMBRE"
    )

    # =========================
    # BARCODE (CENTRADO MEJOR)
    # =========================
    if mechanic_code:
        barcode = createBarcodeDrawing(
            "Code128",
            value=mechanic_code,
            barHeight=13 * mm,
            barWidth=0.42 * mm,
            humanReadable=False,
        )

        barcode_x = (width - barcode.width) / 2
        barcode_y = 18 * mm   # 🔥 SUBIDO UN POCO

        renderPDF.draw(barcode, pdf, barcode_x, barcode_y)

    # =========================
    # CÓDIGO TEXTO (VISIBLE)
    # =========================
    pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(
        width / 2,
        12 * mm,   # 🔥 SUBIDO (antes muy abajo)
        mechanic_code or "SIN CÓDIGO"
    )

    pdf.showPage()
    pdf.save()

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes