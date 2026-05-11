from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.extensions import db
from app.models.article import Article
from app.models.mechanic import Mechanic
from app.models.tool_loan import ToolLoan
from app.models.warehouse import Warehouse
from app.services.inventory_service import (
    InventoryServiceError,
    add_stock,
    subtract_stock,
)


class ToolLoanServiceError(Exception):
    pass


TOOL_STATUS_REQUESTED = "SOLICITADA"
TOOL_STATUS_LOANED = "PRESTADA"
TOOL_STATUS_RETURN_REQUESTED = "DEVOLUCION_SOLICITADA"
TOOL_STATUS_RETURNED = "DEVUELTA"
TOOL_STATUS_CANCELLED = "CANCELADA"


def _normalize_decimal(value: Any, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ToolLoanServiceError(f"Valor inválido para {field_name}.") from exc

    return amount


def _is_tool_article_code(code: str | None) -> bool:
    try:
        number = int(str(code or "").strip())
        return 19000 <= number <= 19999
    except Exception:
        return False


def _get_mechanic_or_error(
    *,
    mechanic_id: int,
    site_id: int | None = None,
) -> Mechanic:
    query = Mechanic.query.filter(
        Mechanic.id == mechanic_id,
        Mechanic.is_active.is_(True),
    )

    if site_id:
        query = query.filter(Mechanic.site_id == site_id)

    mechanic = query.first()

    if not mechanic:
        raise ToolLoanServiceError("Mecánico no encontrado o inactivo.")

    return mechanic


def _get_article_or_error(article_id: int) -> Article:
    article = Article.query.get(article_id)

    if not article:
        raise ToolLoanServiceError("La herramienta indicada no existe.")

    if not _is_tool_article_code(article.code):
        raise ToolLoanServiceError(
            "El artículo indicado no pertenece a la familia de herramientas."
        )

    if hasattr(article, "is_active") and not article.is_active:
        raise ToolLoanServiceError("La herramienta indicada está inactiva.")

    return article


def _get_warehouse_or_error(warehouse_id: int) -> Warehouse:
    warehouse = Warehouse.query.get(warehouse_id)

    if not warehouse:
        raise ToolLoanServiceError("La bodega indicada no existe.")

    if hasattr(warehouse, "is_active") and not warehouse.is_active:
        raise ToolLoanServiceError("La bodega indicada está inactiva.")

    return warehouse


def request_tool_loan_by_mechanic(
    *,
    mechanic_id: int,
    article_id: int,
    warehouse_id: int,
    quantity: Any = 1,
    requested_by_user_id: int,
    notes: str | None = None,
    site_id: int | None = None,
    work_order_id: int | None = None,
    commit: bool = True,
) -> ToolLoan:
    mechanic = _get_mechanic_or_error(
        mechanic_id=mechanic_id,
        site_id=site_id,
    )

    article = _get_article_or_error(article_id)
    _get_warehouse_or_error(warehouse_id)

    qty = _normalize_decimal(quantity, "cantidad")

    if qty <= 0:
        raise ToolLoanServiceError("La cantidad debe ser mayor que cero.")

    loan = ToolLoan(
        work_order_id=work_order_id,
        request_line_id=None,
        article_id=article.id,
        warehouse_id=warehouse_id,
        mechanic_id=mechanic.id,
        requested_by_user_id=requested_by_user_id,
        quantity=qty,
        loan_status=TOOL_STATUS_REQUESTED,
        notes=(notes or "").strip() or None,
        loaned_at=datetime.now(UTC),
    )

    db.session.add(loan)

    if commit:
        db.session.commit()

    return loan


def deliver_tool_loan(
    *,
    tool_loan_id: int,
    delivered_by_user_id: int,
    commit: bool = True,
) -> ToolLoan:
    loan = ToolLoan.query.get(tool_loan_id)

    if not loan:
        raise ToolLoanServiceError("El préstamo de herramienta no existe.")

    if loan.loan_status != TOOL_STATUS_REQUESTED:
        raise ToolLoanServiceError(
            "Solo se pueden entregar herramientas en estado SOLICITADA."
        )

    try:
        subtract_stock(
            article_id=loan.article_id,
            warehouse_id=loan.warehouse_id,
            quantity=loan.quantity,
            performed_by_user_id=delivered_by_user_id,
            movement_type="PRESTAMO_HERRAMIENTA",
            reason="Préstamo de herramienta a mecánico",
            reference_type="TOOL_LOAN",
            reference_id=loan.id,
            reference_number=str(loan.id),
            commit=False,
        )
    except InventoryServiceError as exc:
        db.session.rollback()
        raise ToolLoanServiceError(str(exc)) from exc

    loan.loan_status = TOOL_STATUS_LOANED
    loan.delivered_by_user_id = delivered_by_user_id
    loan.loaned_at = datetime.now(UTC)

    if commit:
        db.session.commit()

    return loan


def list_active_tool_loans(
    *,
    site_id: int | None = None,
) -> list[ToolLoan]:
    query = ToolLoan.query.filter(
        ToolLoan.loan_status.in_(
            [
                TOOL_STATUS_LOANED,
                TOOL_STATUS_RETURN_REQUESTED,
            ]
        )
    )

    if site_id:
        query = (
            query
            .join(Warehouse, Warehouse.id == ToolLoan.warehouse_id)
            .filter(Warehouse.site_id == site_id)
        )

    return (
        query
        .order_by(
            ToolLoan.loaned_at.desc(),
            ToolLoan.id.desc(),
        )
        .all()
    )


def list_requested_tool_loans(
    *,
    site_id: int | None = None,
) -> list[ToolLoan]:
    query = ToolLoan.query.filter(
        ToolLoan.loan_status == TOOL_STATUS_REQUESTED
    )

    if site_id:
        query = (
            query
            .join(Warehouse, Warehouse.id == ToolLoan.warehouse_id)
            .filter(Warehouse.site_id == site_id)
        )

    return (
        query
        .order_by(
            ToolLoan.loaned_at.asc(),
            ToolLoan.id.asc(),
        )
        .all()
    )


def list_mechanic_tool_loans(
    *,
    mechanic_id: int,
    site_id: int | None = None,
) -> list[ToolLoan]:
    mechanic = _get_mechanic_or_error(
        mechanic_id=mechanic_id,
        site_id=site_id,
    )

    return (
        ToolLoan.query
        .filter(
            ToolLoan.mechanic_id == mechanic.id,
            ToolLoan.loan_status.in_(
                [
                    TOOL_STATUS_REQUESTED,
                    TOOL_STATUS_LOANED,
                    TOOL_STATUS_RETURN_REQUESTED,
                ]
            ),
        )
        .order_by(
            ToolLoan.loaned_at.desc(),
            ToolLoan.id.desc(),
        )
        .all()
    )


def request_tool_return(
    *,
    tool_loan_id: int,
    mechanic_id: int,
    returned_by_user_id: int,
    site_id: int | None = None,
    commit: bool = True,
) -> ToolLoan:
    mechanic = _get_mechanic_or_error(
        mechanic_id=mechanic_id,
        site_id=site_id,
    )

    loan = ToolLoan.query.get(tool_loan_id)

    if not loan:
        raise ToolLoanServiceError("El préstamo de herramienta no existe.")

    if loan.mechanic_id != mechanic.id:
        raise ToolLoanServiceError(
            "Esta herramienta no está asignada al mecánico indicado."
        )

    if loan.loan_status != TOOL_STATUS_LOANED:
        raise ToolLoanServiceError(
            "Solo se pueden solicitar devoluciones de herramientas prestadas."
        )

    loan.loan_status = TOOL_STATUS_RETURN_REQUESTED
    loan.returned_by_user_id = returned_by_user_id
    loan.returned_at = datetime.now(UTC)

    if commit:
        db.session.commit()

    return loan


def request_all_tool_returns(
    *,
    mechanic_id: int,
    returned_by_user_id: int,
    site_id: int | None = None,
    commit: bool = True,
) -> list[ToolLoan]:
    mechanic = _get_mechanic_or_error(
        mechanic_id=mechanic_id,
        site_id=site_id,
    )

    loans = (
        ToolLoan.query
        .filter(
            ToolLoan.mechanic_id == mechanic.id,
            ToolLoan.loan_status == TOOL_STATUS_LOANED,
        )
        .order_by(ToolLoan.loaned_at.asc())
        .all()
    )

    if not loans:
        raise ToolLoanServiceError(
            "El mecánico no tiene herramientas prestadas para devolver."
        )

    now = datetime.now(UTC)

    for loan in loans:
        loan.loan_status = TOOL_STATUS_RETURN_REQUESTED
        loan.returned_by_user_id = returned_by_user_id
        loan.returned_at = now

    if commit:
        db.session.commit()

    return loans


def receive_tool_return(
    *,
    tool_loan_id: int,
    received_by_user_id: int,
    commit: bool = True,
) -> ToolLoan:
    loan = ToolLoan.query.get(tool_loan_id)

    if not loan:
        raise ToolLoanServiceError("El préstamo de herramienta no existe.")

    if loan.loan_status != TOOL_STATUS_RETURN_REQUESTED:
        raise ToolLoanServiceError(
            "Solo se pueden recibir herramientas con devolución solicitada."
        )

    try:
        add_stock(
            article_id=loan.article_id,
            warehouse_id=loan.warehouse_id,
            quantity=loan.quantity,
            performed_by_user_id=received_by_user_id,
            movement_type="DEVOLUCION_HERRAMIENTA",
            reason="Devolución de herramienta prestada",
            reference_type="TOOL_LOAN",
            reference_id=loan.id,
            reference_number=str(loan.id),
            commit=False,
        )
    except InventoryServiceError as exc:
        db.session.rollback()
        raise ToolLoanServiceError(str(exc)) from exc

    loan.loan_status = TOOL_STATUS_RETURNED
    loan.received_return_by_user_id = received_by_user_id
    loan.returned_at = datetime.now(UTC)

    if commit:
        db.session.commit()

    return loan


def cancel_requested_tool_loan(
    *,
    tool_loan_id: int,
    cancelled_by_user_id: int,
    commit: bool = True,
) -> ToolLoan:
    loan = ToolLoan.query.get(tool_loan_id)

    if not loan:
        raise ToolLoanServiceError("El préstamo de herramienta no existe.")

    if loan.loan_status != TOOL_STATUS_REQUESTED:
        raise ToolLoanServiceError(
            "Solo se pueden cancelar solicitudes de herramientas no entregadas."
        )

    loan.loan_status = TOOL_STATUS_CANCELLED
    loan.returned_by_user_id = cancelled_by_user_id
    loan.returned_at = datetime.now(UTC)

    if commit:
        db.session.commit()

    return loan