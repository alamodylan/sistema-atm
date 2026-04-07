from __future__ import annotations

from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.colors import black, white
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def build_mechanic_badge_pdf(mechanic) -> bytes:
    """
    Genera un gafete en PDF con nombre, código alfanumérico y código de barras.
    Retorna los bytes del PDF.
    """

    buffer = BytesIO()

    # Tamaño tipo credencial horizontal
    width = 90 * mm
    height = 55 * mm

    pdf = canvas.Canvas(buffer, pagesize=(width, height))

    # Fondo blanco
    pdf.setFillColor(white)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)

    # Borde
    pdf.setStrokeColor(black)
    pdf.setLineWidth(1)
    pdf.rect(4, 4, width - 8, height - 8, fill=0, stroke=1)

    # Título
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawCentredString(width / 2, height - 12 * mm, "GAFETE")

    # Nombre del mecánico
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(width / 2, height - 22 * mm, mechanic.name or "")

    # Código de barras
    barcode_value = (mechanic.code or "").strip()

    if barcode_value:
        barcode = createBarcodeDrawing(
            "Code128",
            value=barcode_value,
            barHeight=14 * mm,
            barWidth=0.45 * mm,
            humanReadable=False,
        )

        barcode_width = barcode.width
        barcode_height = barcode.height

        x = (width - barcode_width) / 2
        y = 14 * mm

        renderPDF.draw(barcode, pdf, x, y)

    # Código alfanumérico visible
    pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(width / 2, 8 * mm, barcode_value)

    pdf.showPage()
    pdf.save()

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes