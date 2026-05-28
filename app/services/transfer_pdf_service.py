from io import BytesIO
import os
from zoneinfo import ZoneInfo

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)

from app.models.transfer_event import TransferEvent
from app.models.user import User


def _text(value):
    if value is None:
        return ""
    return str(value)


def _format_datetime(dt):
    if not dt:
        return ""

    try:
        cr_tz = ZoneInfo("America/Costa_Rica")

        local_dt = dt.astimezone(cr_tz)

        return local_dt.strftime("%d/%m/%Y %I:%M %p")

    except Exception:
        return str(dt)


def _user_name(user_id):
    if not user_id:
        return ""

    user = User.query.get(user_id)

    if not user:
        return ""

    return user.full_name or user.username or ""


def _get_sender_user_id(transfer):
    event = (
        TransferEvent.query
        .filter(
            TransferEvent.transfer_id == transfer.id,
            TransferEvent.event_type == "ENVIADO",
        )
        .order_by(TransferEvent.created_at.desc())
        .first()
    )

    if event:
        return event.performed_by_user_id

    return transfer.created_by_user_id


def generate_transfer_pdf(transfer):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TransferTitle",
        parent=styles["Title"],
        fontSize=16,
        leading=20,
        alignment=1,
        textColor=colors.HexColor("#003B7A"),
        spaceAfter=10,
    )

    normal_style = styles["Normal"]
    normal_style.fontSize = 9
    normal_style.leading = 12

    story = []

    logo_path = os.path.join(
        current_app.root_path,
        "static",
        "img",
        "logo.png",
    )

    header_data = []

    if os.path.exists(logo_path):
        logo = Image(
            logo_path,
            width=4.2 * cm,
            height=2.0 * cm,
        )
    else:
        logo = Paragraph(
            "<b>ATM</b>",
            styles["Heading2"],
        )

    header_data.append([
        logo,
        Paragraph(
            "<b>Álamo Terminales Marítimos</b><br/>"
            "Sistema de Bodega y Taller<br/>"
            "Documento de traslado interno",
            normal_style,
        ),
    ])

    header_table = Table(
        header_data,
        colWidths=[5 * cm, 12 * cm],
    )

    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    story.append(header_table)
    story.append(Spacer(1, 12))

    story.append(
        Paragraph(
            "COMPROBANTE DE TRASLADO",
            title_style,
        )
    )

    sender_user_id = _get_sender_user_id(transfer)

    sender_name = _user_name(sender_user_id)

    receiver_name = _user_name(
        transfer.received_by_user_id
    )

    info_data = [
        ["Número de traslado", _text(transfer.number)],

        ["Estado", _text(transfer.status)],

        [
            "Fecha de creación",
            _format_datetime(transfer.created_at),
        ],

        [
            "Fecha de envío",
            _format_datetime(transfer.sent_at),
        ],

        [
            "Fecha de recepción",
            _format_datetime(transfer.received_at),
        ],

        [
            "Predio origen",
            _text(
                transfer.origin_site.name
                if transfer.origin_site else ""
            ),
        ],

        [
            "Bodega origen",
            _text(
                transfer.origin_warehouse.name
                if transfer.origin_warehouse else ""
            ),
        ],

        [
            "Predio destino",
            _text(
                transfer.destination_site.name
                if transfer.destination_site else ""
            ),
        ],

        [
            "Bodega destino",
            _text(
                transfer.destination_warehouse.name
                if transfer.destination_warehouse else ""
            ),
        ],

        ["Enviado por", sender_name],

        ["Recibido por", receiver_name],

        ["Notas", _text(transfer.notes)],
    ]

    info_table = Table(
        info_data,
        colWidths=[5 * cm, 12 * cm],
    )

    info_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4FF")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#003B7A")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(info_table)

    story.append(Spacer(1, 14))

    story.append(
        Paragraph(
            "<b>Detalle de artículos trasladados</b>",
            styles["Heading3"],
        )
    )

    story.append(Spacer(1, 6))

    lines_data = [
        [
            "Código",
            "Artículo",
            "Cantidad enviada",
            "Cantidad recibida",
            "Estado",
        ]
    ]

    for line in transfer.lines:
        article = line.article

        lines_data.append([
            _text(article.code if article else line.article_id),

            Paragraph(
                _text(article.name if article else ""),
                normal_style,
            ),

            _text(line.quantity_sent),

            _text(
                line.quantity_received
                if line.quantity_received is not None else ""
            ),

            _text(line.line_status),
        ])

    lines_table = Table(
        lines_data,
        colWidths=[2.5 * cm, 7.0 * cm, 3.0 * cm, 3.0 * cm, 2.5 * cm],
        repeatRows=1,
    )

    lines_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003B7A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(lines_table)

    story.append(Spacer(1, 28))

    signature_data = [
        [
            Paragraph(
                "<b>Firma de quien envía</b>",
                normal_style,
            ),

            Paragraph(
                "<b>Firma de quien recibe</b>",
                normal_style,
            ),
        ],

        [
            "",
            "",
        ],

        [
            f"Nombre: {sender_name}",
            "Nombre: ______________________________",
        ],

        [
            "Firma: ______________________________",
            "Firma: ______________________________",
        ],

        [
            "Fecha: ______________________________",
            "Fecha: ______________________________",
        ],
    ]

    signature_table = Table(
        signature_data,
        colWidths=[8.5 * cm, 8.5 * cm],
        rowHeights=[0.7 * cm, 1.2 * cm, 0.7 * cm, 0.7 * cm, 0.7 * cm],
    )

    signature_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))

    story.append(signature_table)

    doc.build(story)

    buffer.seek(0)

    return buffer