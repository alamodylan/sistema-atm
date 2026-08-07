from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_approval import PurchaseOrderApproval
from app.models.purchase_order_candidate import PurchaseOrderCandidate
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_line import PurchaseRequestLine
from app.models.quotation_line import QuotationLine
from app.models.article import Article
from app.models.pending_article import PendingArticle
from app.models.supplier import Supplier
from app.models.site import Site
from app.models.unit import Unit
from app.models.warehouse import Warehouse


class PurchaseOrderServiceError(Exception):
    pass




def _generate_purchase_order_number() -> str:
    max_id = db.session.query(func.max(PurchaseOrder.id)).scalar() or 0
    next_id = int(max_id) + 1
    return f"OC-{next_id:06d}"


def _normalize_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise PurchaseOrderServiceError(f"Valor inválido para {field_name}.") from exc


def _normalize_candidate_ids(
    candidate_ids: list[int] | None,
) -> list[int]:
    """
    Normaliza y valida los identificadores de candidatos recibidos
    para generar una orden de compra.
    """

    if not candidate_ids:
        raise PurchaseOrderServiceError(
            "Debe seleccionar al menos una línea pendiente para crear la orden."
        )

    normalized_ids: list[int] = []

    for candidate_id in candidate_ids:
        try:
            normalized_id = int(candidate_id)
        except (TypeError, ValueError) as exc:
            raise PurchaseOrderServiceError(
                "Se recibió una selección de pre-OC inválida."
            ) from exc

        if normalized_id <= 0:
            raise PurchaseOrderServiceError(
                "Se recibió una selección de pre-OC inválida."
            )

        normalized_ids.append(normalized_id)

    if len(normalized_ids) != len(set(normalized_ids)):
        raise PurchaseOrderServiceError(
            "Una misma línea fue seleccionada más de una vez."
        )

    return normalized_ids

def _build_payment_terms(
    quotation_line: QuotationLine,
) -> str | None:
    """
    Construye el texto de condiciones de pago de una cotización.
    """

    payment_type = (
        quotation_line.payment_type or ""
    ).strip()

    payment_term_months = (
        quotation_line.payment_term_months
    )

    if not payment_type:
        return None

    if payment_term_months is not None:
        return (
            f"{payment_type} "
            f"{payment_term_months} meses"
        )

    return payment_type

def _calculate_purchase_order_line_amounts(
    *,
    quotation_line: QuotationLine,
    quantity: Any,
) -> dict:
    """
    Calcula los montos de una línea de orden desde su cotización.

    unit_cost representa el costo unitario antes del descuento
    y sin impuesto.

    El descuento y el impuesto permanecen almacenados por separado
    en PurchaseOrderLine.
    """

    quantity_decimal = _normalize_decimal(
        quantity,
        "cantidad ordenada",
    )

    unit_price = _normalize_decimal(
        quotation_line.unit_price or Decimal("0"),
        "precio unitario",
    )

    discount_pct = _normalize_decimal(
        quotation_line.discount_pct or Decimal("0"),
        "descuento",
    )

    tax_pct = _normalize_decimal(
        quotation_line.tax_pct or Decimal("0"),
        "impuesto",
    )

    if quantity_decimal <= 0:
        raise PurchaseOrderServiceError(
            "La cantidad ordenada debe ser mayor que cero."
        )

    if unit_price <= 0:
        raise PurchaseOrderServiceError(
            "La cotización seleccionada no tiene un precio válido."
        )

    if discount_pct < 0 or discount_pct > 100:
        raise PurchaseOrderServiceError(
            "El porcentaje de descuento debe estar entre 0 y 100."
        )

    if tax_pct < 0:
        raise PurchaseOrderServiceError(
            "El porcentaje de impuesto no puede ser negativo."
        )

    tax_factor = (
        Decimal("1")
        + (tax_pct / Decimal("100"))
    )

    if quotation_line.tax_included:
        unit_cost = (
            unit_price / tax_factor
            if tax_pct > 0
            else unit_price
        )
    else:
        unit_cost = unit_price

    line_subtotal = (
        quantity_decimal * unit_cost
    )

    discount_amount = (
        line_subtotal
        * (discount_pct / Decimal("100"))
    )

    taxable_base = (
        line_subtotal - discount_amount
    )

    tax_amount = (
        taxable_base
        * (tax_pct / Decimal("100"))
    )

    line_total = (
        taxable_base + tax_amount
    )

    return {
        "quantity": quantity_decimal,
        "unit_cost": unit_cost,
        "discount_pct": discount_pct,
        "tax_pct": tax_pct,
        "line_subtotal": line_subtotal,
        "discount_amount": discount_amount,
        "taxable_base": taxable_base,
        "tax_amount": tax_amount,
        "line_total": line_total,
    }

def _update_purchase_request_after_order_creation(
    purchase_request_id: int,
) -> None:
    """
    Actualiza el estado general de una solicitud cuando sus líneas
    han sido convertidas en órdenes de compra.

    La solicitud solamente pasa a CONVERTIDA_A_OC cuando todas sus
    líneas activas fueron convertidas o recibidas.
    """

    purchase_request = PurchaseRequest.query.get(
        purchase_request_id
    )

    if not purchase_request:
        return

    if purchase_request.status in {
        "CERRADA",
        "CANCELADA",
    }:
        return

    active_lines = [
        line
        for line in purchase_request.lines
        if line.line_status != "CANCELADA"
    ]

    if not active_lines:
        return

    completed_statuses = {
        "CONVERTIDA_A_OC",
        "RECIBIDA",
    }

    if all(
        line.line_status in completed_statuses
        for line in active_lines
    ):
        purchase_request.status = (
            "CONVERTIDA_A_OC"
        )



def create_purchase_order(
    *,
    candidate_ids: list[int],
    generated_by_user_id: int,
    supplier_id: int | None = None,
    notes: str | None = None,
    payment_terms: str | None = None,
) -> PurchaseOrder:
    """
    Crea una orden de compra exclusivamente desde candidatos de pre-OC.

    Reglas:
    - todos los candidatos deben estar en estado PENDING;
    - ninguno puede estar vinculado previamente a una OC;
    - todos deben pertenecer al mismo proveedor;
    - todos deben utilizar la misma moneda;
    - cada candidato debe coincidir con su cotización y solicitud;
    - ninguna línea de solicitud puede haberse utilizado previamente;
    - después de crear la OC:
        PurchaseOrderCandidate -> USED
        QuotationLine -> CONVERTIDA_A_OC
        PurchaseRequestLine -> CONVERTIDA_A_OC
    """

    if not generated_by_user_id:
        raise PurchaseOrderServiceError(
            "No se pudo identificar el usuario que genera la orden."
        )

    normalized_candidate_ids = (
        _normalize_candidate_ids(
            candidate_ids
        )
    )

    try:
        candidates = (
            PurchaseOrderCandidate.query
            .filter(
                PurchaseOrderCandidate.id.in_(
                    normalized_candidate_ids
                )
            )
            .with_for_update()
            .order_by(
                PurchaseOrderCandidate.id.asc()
            )
            .all()
        )

        returned_candidate_ids = {
            candidate.id
            for candidate in candidates
        }

        expected_candidate_ids = set(
            normalized_candidate_ids
        )

        if (
            returned_candidate_ids
            != expected_candidate_ids
        ):
            raise PurchaseOrderServiceError(
                "Una o más selecciones de pre-OC no existen."
            )

        candidate_supplier_ids = {
            candidate.supplier_id
            for candidate in candidates
        }

        if len(candidate_supplier_ids) != 1:
            raise PurchaseOrderServiceError(
                "Todos los candidatos de una orden deben pertenecer al mismo proveedor."
            )

        resolved_supplier_id = next(
            iter(candidate_supplier_ids)
        )

        if (
            supplier_id is not None
            and int(supplier_id)
            != resolved_supplier_id
        ):
            raise PurchaseOrderServiceError(
                "El proveedor indicado no coincide con los candidatos seleccionados."
            )

        quotation_lines: list[
            QuotationLine
        ] = []

        request_lines: list[
            PurchaseRequestLine
        ] = []

        currency_codes: set[str] = set()
        purchase_request_ids: set[int] = set()
        site_ids: set[int] = set()
        warehouse_ids: set[int] = set()
        detected_payment_terms: set[str] = set()

        for index, candidate in enumerate(
            candidates,
            start=1,
        ):
            if candidate.status != "PENDING":
                raise PurchaseOrderServiceError(
                    f"La selección de la línea {index} ya no está pendiente."
                )

            if candidate.purchase_order_id is not None:
                raise PurchaseOrderServiceError(
                    f"La selección de la línea {index} ya está vinculada a una orden de compra."
                )

            quotation_line = (
                QuotationLine.query
                .filter(
                    QuotationLine.id
                    == candidate.quotation_line_id
                )
                .with_for_update()
                .first()
            )

            if not quotation_line:
                raise PurchaseOrderServiceError(
                    f"La cotización de la línea {index} no existe."
                )

            request_line = (
                PurchaseRequestLine.query
                .filter(
                    PurchaseRequestLine.id
                    == candidate.purchase_request_line_id
                )
                .with_for_update()
                .first()
            )

            if not request_line:
                raise PurchaseOrderServiceError(
                    f"La línea de solicitud correspondiente a la selección {index} no existe."
                )

            if (
                quotation_line.purchase_request_line_id
                != request_line.id
            ):
                raise PurchaseOrderServiceError(
                    f"La cotización de la línea {index} no corresponde a la solicitud seleccionada."
                )

            if (
                quotation_line.supplier_id
                != resolved_supplier_id
                or candidate.supplier_id
                != resolved_supplier_id
            ):
                raise PurchaseOrderServiceError(
                    f"La línea {index} pertenece a otro proveedor."
                )

            if quotation_line.status in {
                "BORRADOR",
                "DESCARTADA",
                "CONVERTIDA_A_OC",
            }:
                raise PurchaseOrderServiceError(
                    f"La cotización de la línea {index} no está disponible para generar una orden."
                )

            if request_line.line_status in {
                "CANCELADA",
                "CONVERTIDA_A_OC",
                "RECIBIDA",
            }:
                raise PurchaseOrderServiceError(
                    f"La línea de solicitud {index} ya no está disponible para generar una orden."
                )

            if bool(
                quotation_line.article_id
            ) == bool(
                quotation_line.pending_article_id
            ):
                raise PurchaseOrderServiceError(
                    f"La cotización de la línea {index} debe tener un artículo normal o pendiente, pero no ambos."
                )

            existing_quotation_usage = (
                PurchaseOrderLine.query
                .filter(
                    PurchaseOrderLine.quotation_line_id
                    == quotation_line.id
                )
                .first()
            )

            if existing_quotation_usage:
                raise PurchaseOrderServiceError(
                    f"La cotización de la línea {index} ya fue utilizada en otra orden."
                )

            existing_request_usage = (
                PurchaseOrderLine.query
                .filter(
                    PurchaseOrderLine.purchase_request_line_id
                    == request_line.id
                )
                .first()
            )

            if existing_request_usage:
                raise PurchaseOrderServiceError(
                    f"La línea de solicitud {index} ya fue utilizada en otra orden."
                )

            currency_code = (
                quotation_line.currency_code
                or "CRC"
            ).strip().upper()

            currency_codes.add(
                currency_code
            )

            purchase_request_id = (
                request_line.purchase_request_id
            )

            if purchase_request_id:
                purchase_request_ids.add(
                    purchase_request_id
                )

            purchase_request = (
                request_line.purchase_request
            )

            if purchase_request:
                if purchase_request.site_id:
                    site_ids.add(
                        purchase_request.site_id
                    )

                if purchase_request.warehouse_id:
                    warehouse_ids.add(
                        purchase_request.warehouse_id
                    )

            quotation_payment_terms = (
                _build_payment_terms(
                    quotation_line
                )
            )

            if quotation_payment_terms:
                detected_payment_terms.add(
                    quotation_payment_terms
                )

            quotation_lines.append(
                quotation_line
            )

            request_lines.append(
                request_line
            )

        if len(currency_codes) != 1:
            raise PurchaseOrderServiceError(
                "Una orden de compra solo puede contener líneas de una misma moneda."
            )

        resolved_currency_code = next(
            iter(currency_codes)
        )

        resolved_purchase_request_id = (
            next(iter(purchase_request_ids))
            if len(purchase_request_ids) == 1
            else None
        )

        resolved_site_id = (
            next(iter(site_ids))
            if len(site_ids) == 1
            else None
        )

        resolved_warehouse_id = (
            next(iter(warehouse_ids))
            if len(warehouse_ids) == 1
            else None
        )

        resolved_payment_terms = (
            (payment_terms or "").strip()
            or (
                next(iter(detected_payment_terms))
                if len(detected_payment_terms) == 1
                else None
            )
        )

        now = datetime.now(UTC)

        purchase_order = PurchaseOrder(
            number=_generate_purchase_order_number(),
            purchase_request_id=(
                resolved_purchase_request_id
            ),
            supplier_id=resolved_supplier_id,
            site_id=resolved_site_id,
            warehouse_id=resolved_warehouse_id,
            generated_by_user_id=(
                generated_by_user_id
            ),
            approval_status=(
                "PENDIENTE_APROBACION"
            ),
            submitted_for_approval_at=now,
            payment_terms=(
                resolved_payment_terms
            ),
            currency_code=(
                resolved_currency_code
            ),
            notes=(
                (notes or "").strip()
                or None
            ),
        )

        db.session.add(
            purchase_order
        )

        db.session.flush()

        affected_purchase_request_ids: set[
            int
        ] = set()

        for (
            candidate,
            quotation_line,
            request_line,
        ) in zip(
            candidates,
            quotation_lines,
            request_lines,
        ):
            quantity = _normalize_decimal(
                request_line.quantity_requested
                or Decimal("0"),
                "cantidad solicitada",
            )

            amounts = (
                _calculate_purchase_order_line_amounts(
                    quotation_line=quotation_line,
                    quantity=quantity,
                )
            )

            unit_id = request_line.unit_id

            if (
                not unit_id
                and quotation_line.article
                and quotation_line.article.unit_id
            ):
                unit_id = (
                    quotation_line.article.unit_id
                )

            purchase_order_line = (
                PurchaseOrderLine(
                    purchase_order_id=(
                        purchase_order.id
                    ),
                    purchase_request_line_id=(
                        request_line.id
                    ),
                    quotation_line_id=(
                        quotation_line.id
                    ),
                    article_id=(
                        quotation_line.article_id
                    ),
                    pending_article_id=(
                        quotation_line.pending_article_id
                    ),
                    quantity_ordered=(
                        amounts["quantity"]
                    ),
                    quantity_received=Decimal("0"),
                    unit_id=unit_id,
                    unit_cost=(
                        amounts["unit_cost"]
                    ),
                    discount_pct=(
                        amounts["discount_pct"]
                    ),
                    tax_pct=(
                        amounts["tax_pct"]
                    ),
                    line_subtotal=(
                        amounts["line_subtotal"]
                    ),
                    line_total=(
                        amounts["line_total"]
                    ),
                    line_notes=(
                        quotation_line.notes
                    ),
                )
            )

            db.session.add(
                purchase_order_line
            )

            candidate.status = "USED"
            candidate.purchase_order_id = (
                purchase_order.id
            )
            candidate.updated_at = now

            quotation_line.status = (
                "CONVERTIDA_A_OC"
            )

            request_line.line_status = (
                "CONVERTIDA_A_OC"
            )

            if request_line.purchase_request_id:
                affected_purchase_request_ids.add(
                    request_line.purchase_request_id
                )

        db.session.flush()

        for affected_request_id in (
            affected_purchase_request_ids
        ):
            _update_purchase_request_after_order_creation(
                affected_request_id
            )

        db.session.commit()

        return purchase_order

    except PurchaseOrderServiceError:
        db.session.rollback()
        raise

    except Exception as exc:
        db.session.rollback()

        raise PurchaseOrderServiceError(
            "No fue posible generar la orden de compra."
        ) from exc


def create_manual_purchase_order(
    *,
    supplier_id: int,
    generated_by_user_id: int,
    warehouse_id: int | None,
    site_id: int | None,
    currency_code: str,
    payment_terms: str | None,
    notes: str | None,
    lines: list[dict],
) -> PurchaseOrder:
    """
    Crea una orden de compra manual sin cotización ni solicitud.

    No utiliza:
    - PurchaseRequest
    - PurchaseRequestLine
    - QuotationLine
    - PurchaseOrderCandidate

    Cada línea debe contener:

        {
            "article_id": 1,
            "pending_article_id": None,
            "quantity": "5",
            "unit_id": 1,
            "unit_cost": "1200",
            "discount_pct": "0",
            "tax_pct": "13",
            "notes": "Opcional"
        }
    """

    if not generated_by_user_id:
        raise PurchaseOrderServiceError(
            "No se pudo identificar el usuario que genera la orden."
        )

    try:
        supplier_id = int(supplier_id)

    except (TypeError, ValueError) as exc:
        raise PurchaseOrderServiceError(
            "El proveedor seleccionado no es válido."
        ) from exc

    if supplier_id <= 0:
        raise PurchaseOrderServiceError(
            "Debe seleccionar un proveedor."
        )

    supplier = (
        Supplier.query
        .filter(
            Supplier.id == supplier_id,
            Supplier.is_active.is_(True),
        )
        .first()
    )

    if not supplier:
        raise PurchaseOrderServiceError(
            "El proveedor seleccionado no existe o está inactivo."
        )

    normalized_site_id = None

    if site_id not in {None, ""}:
        try:
            normalized_site_id = int(site_id)

        except (TypeError, ValueError) as exc:
            raise PurchaseOrderServiceError(
                "El predio seleccionado no es válido."
            ) from exc

        site = (
            Site.query
            .filter(
                Site.id == normalized_site_id,
                Site.is_active.is_(True),
            )
            .first()
        )

        if not site:
            raise PurchaseOrderServiceError(
                "El predio seleccionado no existe o está inactivo."
            )

    normalized_warehouse_id = None

    if warehouse_id not in {None, ""}:
        try:
            normalized_warehouse_id = int(
                warehouse_id
            )

        except (TypeError, ValueError) as exc:
            raise PurchaseOrderServiceError(
                "La bodega seleccionada no es válida."
            ) from exc

        warehouse = (
            Warehouse.query
            .filter(
                Warehouse.id
                == normalized_warehouse_id,
                Warehouse.is_active.is_(True),
            )
            .first()
        )

        if not warehouse:
            raise PurchaseOrderServiceError(
                "La bodega seleccionada no existe o está inactiva."
            )

        if (
            normalized_site_id
            and warehouse.site_id
            and warehouse.site_id
            != normalized_site_id
        ):
            raise PurchaseOrderServiceError(
                "La bodega seleccionada no corresponde al predio indicado."
            )

    normalized_currency_code = (
        currency_code
        or "CRC"
    ).strip().upper()

    if normalized_currency_code not in {
        "CRC",
        "USD",
        "EUR",
    }:
        raise PurchaseOrderServiceError(
            "La moneda seleccionada no es válida."
        )

    normalized_payment_terms = (
        payment_terms
        or ""
    ).strip() or None

    normalized_notes = (
        notes
        or ""
    ).strip() or None

    if not isinstance(lines, list) or not lines:
        raise PurchaseOrderServiceError(
            "Debe agregar al menos una línea a la orden."
        )

    normalized_lines = []

    article_ids = set()
    pending_article_ids = set()
    unit_ids = set()

    for index, raw_line in enumerate(
        lines,
        start=1,
    ):
        if not isinstance(raw_line, dict):
            raise PurchaseOrderServiceError(
                f"La línea {index} no es válida."
            )

        article_id = raw_line.get(
            "article_id"
        )

        pending_article_id = raw_line.get(
            "pending_article_id"
        )

        selected_sources = sum(
            [
                bool(article_id),
                bool(pending_article_id),
            ]
        )

        if selected_sources != 1:
            raise PurchaseOrderServiceError(
                f"La línea {index} debe tener un artículo "
                "existente o pendiente, pero no ambos."
            )

        normalized_article_id = None

        if article_id:
            try:
                normalized_article_id = int(
                    article_id
                )

            except (TypeError, ValueError) as exc:
                raise PurchaseOrderServiceError(
                    f"El artículo de la línea {index} no es válido."
                ) from exc

            article_ids.add(
                normalized_article_id
            )

        normalized_pending_article_id = None

        if pending_article_id:
            try:
                normalized_pending_article_id = int(
                    pending_article_id
                )

            except (TypeError, ValueError) as exc:
                raise PurchaseOrderServiceError(
                    f"El artículo pendiente de la línea "
                    f"{index} no es válido."
                ) from exc

            pending_article_ids.add(
                normalized_pending_article_id
            )

        try:
            quantity = _normalize_decimal(
                raw_line.get("quantity"),
                f"cantidad de la línea {index}",
            )

            unit_cost = _normalize_decimal(
                raw_line.get("unit_cost"),
                f"precio unitario de la línea {index}",
            )

            discount_pct = _normalize_decimal(
                raw_line.get(
                    "discount_pct",
                    0,
                ),
                f"descuento de la línea {index}",
            )

            tax_pct = _normalize_decimal(
                raw_line.get(
                    "tax_pct",
                    0,
                ),
                f"impuesto de la línea {index}",
            )

        except PurchaseOrderServiceError:
            raise

        if quantity <= 0:
            raise PurchaseOrderServiceError(
                f"La cantidad de la línea {index} "
                "debe ser mayor que cero."
            )

        if unit_cost <= 0:
            raise PurchaseOrderServiceError(
                f"El precio unitario de la línea {index} "
                "debe ser mayor que cero."
            )

        if (
            discount_pct < 0
            or discount_pct > 100
        ):
            raise PurchaseOrderServiceError(
                f"El descuento de la línea {index} "
                "debe estar entre 0 y 100."
            )

        if tax_pct < 0:
            raise PurchaseOrderServiceError(
                f"El impuesto de la línea {index} "
                "no puede ser negativo."
            )

        unit_id = raw_line.get(
            "unit_id"
        )

        normalized_unit_id = None

        if unit_id not in {None, ""}:
            try:
                normalized_unit_id = int(
                    unit_id
                )

            except (TypeError, ValueError) as exc:
                raise PurchaseOrderServiceError(
                    f"La unidad de la línea {index} "
                    "no es válida."
                ) from exc

            unit_ids.add(
                normalized_unit_id
            )

        line_subtotal = (
            quantity * unit_cost
        )

        discount_amount = (
            line_subtotal
            * (
                discount_pct
                / Decimal("100")
            )
        )

        taxable_base = (
            line_subtotal
            - discount_amount
        )

        tax_amount = (
            taxable_base
            * (
                tax_pct
                / Decimal("100")
            )
        )

        line_total = (
            taxable_base
            + tax_amount
        )

        normalized_lines.append(
            {
                "article_id": (
                    normalized_article_id
                ),
                "pending_article_id": (
                    normalized_pending_article_id
                ),
                "quantity": quantity,
                "unit_id": (
                    normalized_unit_id
                ),
                "unit_cost": unit_cost,
                "discount_pct": discount_pct,
                "tax_pct": tax_pct,
                "line_subtotal": (
                    line_subtotal
                ),
                "line_total": (
                    line_total
                ),
                "notes": (
                    raw_line.get("notes")
                    or ""
                ).strip() or None,
            }
        )

    existing_article_ids = set()

    if article_ids:
        existing_article_ids = {
            row.id
            for row in (
                Article.query
                .filter(
                    Article.id.in_(
                        article_ids
                    ),
                    Article.is_active.is_(True),
                )
                .all()
            )
        }

        missing_article_ids = (
            article_ids
            - existing_article_ids
        )

        if missing_article_ids:
            raise PurchaseOrderServiceError(
                "Uno de los artículos seleccionados "
                "no existe o está inactivo."
            )

    if pending_article_ids:
        existing_pending_ids = {
            row.id
            for row in (
                PendingArticle.query
                .filter(
                    PendingArticle.id.in_(
                        pending_article_ids
                    )
                )
                .all()
            )
        }

        missing_pending_ids = (
            pending_article_ids
            - existing_pending_ids
        )

        if missing_pending_ids:
            raise PurchaseOrderServiceError(
                "Uno de los artículos pendientes "
                "seleccionados no existe."
            )

    if unit_ids:
        existing_unit_ids = {
            row.id
            for row in (
                Unit.query
                .filter(
                    Unit.id.in_(
                        unit_ids
                    )
                )
                .all()
            )
        }

        missing_unit_ids = (
            unit_ids
            - existing_unit_ids
        )

        if missing_unit_ids:
            raise PurchaseOrderServiceError(
                "Una de las unidades seleccionadas no existe."
            )

    try:
        now = datetime.now(UTC)

        purchase_order = PurchaseOrder(
            number=_generate_purchase_order_number(),
            purchase_request_id=None,
            supplier_id=supplier_id,
            site_id=normalized_site_id,
            warehouse_id=(
                normalized_warehouse_id
            ),
            generated_by_user_id=(
                generated_by_user_id
            ),
            approval_status=(
                "PENDIENTE_APROBACION"
            ),
            submitted_for_approval_at=now,
            payment_terms=(
                normalized_payment_terms
            ),
            currency_code=(
                normalized_currency_code
            ),
            notes=normalized_notes,
        )

        db.session.add(
            purchase_order
        )

        db.session.flush()

        for line_data in normalized_lines:
            purchase_order_line = (
                PurchaseOrderLine(
                    purchase_order_id=(
                        purchase_order.id
                    ),
                    purchase_request_line_id=None,
                    quotation_line_id=None,
                    article_id=(
                        line_data[
                            "article_id"
                        ]
                    ),
                    pending_article_id=(
                        line_data[
                            "pending_article_id"
                        ]
                    ),
                    quantity_ordered=(
                        line_data[
                            "quantity"
                        ]
                    ),
                    quantity_received=(
                        Decimal("0")
                    ),
                    unit_id=(
                        line_data[
                            "unit_id"
                        ]
                    ),
                    unit_cost=(
                        line_data[
                            "unit_cost"
                        ]
                    ),
                    discount_pct=(
                        line_data[
                            "discount_pct"
                        ]
                    ),
                    tax_pct=(
                        line_data[
                            "tax_pct"
                        ]
                    ),
                    line_subtotal=(
                        line_data[
                            "line_subtotal"
                        ]
                    ),
                    line_total=(
                        line_data[
                            "line_total"
                        ]
                    ),
                    line_notes=(
                        line_data[
                            "notes"
                        ]
                    ),
                )
            )

            db.session.add(
                purchase_order_line
            )

        db.session.commit()

        return purchase_order

    except PurchaseOrderServiceError:
        db.session.rollback()
        raise

    except Exception as exc:
        db.session.rollback()

        print(
            "[CREATE MANUAL PURCHASE ORDER ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        raise PurchaseOrderServiceError(
            "No fue posible crear la orden "
            "de compra manual."
        ) from exc

def list_purchase_orders(
    *,
    approval_status: str | None = None,
    supplier_id: int | None = None,
    search: str | None = None,
) -> list[PurchaseOrder]:
    query = PurchaseOrder.query

    if approval_status:
        query = query.filter(PurchaseOrder.approval_status == approval_status)

    if supplier_id:
        query = query.filter(PurchaseOrder.supplier_id == supplier_id)

    if search:
        like_value = f"%{search.strip()}%"
        query = query.filter(PurchaseOrder.number.ilike(like_value))

    return query.order_by(
        PurchaseOrder.created_at.desc(),
        PurchaseOrder.id.desc()
    ).all()


def get_purchase_order_or_404(order_id: int) -> PurchaseOrder:
    return PurchaseOrder.query.get_or_404(order_id)


def register_purchase_order_approval(
    *,
    purchase_order_id: int,
    approved_by_user_id: int | None,
    status: str,
    reason: str | None,
) -> PurchaseOrderApproval:
    valid_statuses = {
        "APROBADA",
        "RECHAZADA",
    }

    if status not in valid_statuses:
        raise PurchaseOrderServiceError(
            "Estado de aprobación inválido."
        )

    if not approved_by_user_id:
        raise PurchaseOrderServiceError(
            "No se pudo identificar el usuario que registra la aprobación."
        )

    purchase_order = get_purchase_order_or_404(
        purchase_order_id
    )

    if purchase_order.approval_status in {
        "APROBADA",
        "RECHAZADA",
    }:
        raise PurchaseOrderServiceError(
            "Esta orden de compra ya tiene una decisión de aprobación registrada."
        )

    normalized_reason = (
        reason or ""
    ).strip() or None

    if (
        status == "RECHAZADA"
        and not normalized_reason
    ):
        raise PurchaseOrderServiceError(
            "Debe indicar el motivo del rechazo."
        )

    now = datetime.now(UTC)

    purchase_order.approval_status = status

    if status == "APROBADA":
        purchase_order.approved_at = now

    approval = PurchaseOrderApproval(
        purchase_order_id=purchase_order_id,
        approved_by_user_id=(
            approved_by_user_id
        ),
        status=status,
        reason=normalized_reason,
    )

    db.session.add(
        approval
    )

    db.session.commit()

    return approval

def adjust_approved_purchase_order_line(
    *,
    purchase_order_line_id: int,
    new_quantity: Any,
    new_unit_cost: Any,
) -> PurchaseOrderLine:

    purchase_order_line = PurchaseOrderLine.query.get(
        purchase_order_line_id
    )

    if not purchase_order_line:
        raise PurchaseOrderServiceError(
            "La línea de orden de compra no existe."
        )

    purchase_order = purchase_order_line.purchase_order

    if purchase_order.approval_status != "APROBADA":
        raise PurchaseOrderServiceError(
            "Solo se pueden ajustar órdenes aprobadas."
        )

    quantity = _normalize_decimal(
        new_quantity,
        "cantidad",
    )

    unit_cost = _normalize_decimal(
        new_unit_cost,
        "precio unitario",
    )

    if quantity <= 0:
        raise PurchaseOrderServiceError(
            "La cantidad debe ser mayor que cero."
        )

    if unit_cost <= 0:
        raise PurchaseOrderServiceError(
            "El precio unitario debe ser mayor que cero."
        )

    quantity_received = Decimal(
        str(
            purchase_order_line.quantity_received
            or 0
        )
    )

    if quantity < quantity_received:
        raise PurchaseOrderServiceError(
            "La cantidad ordenada no puede ser menor que la cantidad ya recibida."
        )

    approved_unit_cost = Decimal(
        str(
            purchase_order_line.approved_unit_cost
            or 0
        )
    )

    if unit_cost > approved_unit_cost:
        raise PurchaseOrderServiceError(
            "El precio unitario no puede ser mayor al aprobado."
        )

    discount_pct = Decimal(
        str(
            purchase_order_line.discount_pct
            or 0
        )
    )

    tax_pct = Decimal(
        str(
            purchase_order_line.tax_pct
            or 0
        )
    )

    line_subtotal = (
        quantity
        * unit_cost
    )

    discount_amount = (
        line_subtotal
        * (
            discount_pct
            / Decimal("100")
        )
    )

    taxable_base = (
        line_subtotal
        - discount_amount
    )

    tax_amount = (
        taxable_base
        * (
            tax_pct
            / Decimal("100")
        )
    )

    line_total = (
        taxable_base
        + tax_amount
    )

    approved_line_total = Decimal(
        str(
            purchase_order_line.approved_line_total
            or 0
        )
    )

    if line_total > approved_line_total:
        raise PurchaseOrderServiceError(
            "El monto total de la línea no puede ser mayor al monto aprobado."
        )

    purchase_order_line.quantity_ordered = quantity
    purchase_order_line.unit_cost = unit_cost
    purchase_order_line.line_subtotal = line_subtotal
    purchase_order_line.line_total = line_total

    db.session.commit()

    return purchase_order_line