from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from app.extensions import db
from app.models.article_supplier import ArticleSupplier
from app.models.purchase_request_line import PurchaseRequestLine
from io import BytesIO
from flask import send_file
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from app.models.purchase_order_approval import PurchaseOrderApproval
from app.models.quotation_line import QuotationLine
from app.models.inventory import WarehouseStock
from sqlalchemy import func
from flask import session

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    Response,
)
from flask_login import current_user, login_required

from app.models.article import Article
from app.models.item_category import ItemCategory
from app.models.pending_article import PendingArticle
from app.models.purchase_request import PurchaseRequest
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.unit import Unit
from app.models.warehouse import Warehouse
from app.models.purchase_order import PurchaseOrder
from app.models.quotation_batch import QuotationBatch
from app.models.purchase_order_line import PurchaseOrderLine
from app.services.inventory_entry_service import (
    InventoryEntryLinePayload,
    InventoryEntryServiceError,
    create_inventory_entry,
    get_inventory_entry_or_404,
    list_inventory_entries,
)
from app.services.pending_article_service import (
    PendingArticleServiceError,
    create_pending_article,
    get_pending_article_or_404,
    list_pending_articles,
    resolve_pending_article,
)
from app.services.purchase_order_service import (
    PurchaseOrderLinePayload,
    PurchaseOrderServiceError,
    create_purchase_order,
    get_purchase_order_or_404,
    list_purchase_orders,
    register_purchase_order_approval,
    adjust_approved_purchase_order_line,
)
from app.services.purchase_request_service import (
    PurchaseRequestLinePayload,
    PurchaseRequestServiceError,
    create_purchase_request,
    get_purchase_request_or_404,
    list_purchase_requests,
    submit_purchase_request,
    list_purchase_requests_for_manager_review,
    update_purchase_request_line_by_manager,
    approve_purchase_request_for_quotation,
)
from app.services.quotation_service import (
    QuotationLinePayload,
    QuotationServiceError,
    create_quotation_batch,
    create_single_line_quotation,
    get_quotation_batch_or_404,
    list_quotation_request_groups,
    list_quotation_batches,
    list_quotation_line_groups,
    get_comparison_for_purchase_request_line,
    get_last_price_for_supplier,
)

purchases_bp = Blueprint("purchases", __name__, template_folder="../templates")

CR_TZ = ZoneInfo("America/Costa_Rica")


def _to_int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def _to_decimal(value: str | None, default: str = "0") -> Decimal:
    raw = (value or "").strip()
    try:
        return Decimal(raw if raw else default)
    except (InvalidOperation, TypeError):
        raise ValueError("Valor decimal inválido.")


def _get_valid_purchase_orders_for_receiving():
    return (
        PurchaseOrder.query.filter(
            PurchaseOrder.approval_status.in_(["APROBADA", "RECIBIDA_PARCIAL"])
        )
        .order_by(PurchaseOrder.created_at.desc())
    )


def _cr_datetime(value, fmt: str = "%d/%m/%Y %H:%M") -> str:
    if not value:
        return "-"

    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(CR_TZ).strftime(fmt)
    except Exception:
        return "-"


@purchases_bp.route("/")
@login_required
def home():
    return render_template("purchases/home.html")


# =========================
# SOLICITUDES
# =========================
@purchases_bp.route("/requests")
@login_required
def list_requests():
    status = request.args.get("status", type=str)
    priority = request.args.get("priority", type=str)
    search = request.args.get("search", type=str)

    return render_template(
        "purchases/requests/index.html",
        purchase_requests=[],
        selected_status=status,
        selected_priority=priority,
        search=search,
    )


@purchases_bp.route("/requests/create", methods=["GET", "POST"])
@login_required
def create_request():
    search = (request.args.get("search") or "").strip()

    # IMPORTANTE:
    # Ya no cargamos artículos al abrir la pantalla.
    # Los artículos se buscan por AJAX en:
    # /requests/articles/search
    articles = []

    units = Unit.query.order_by(Unit.id.asc()).all()
    sites = Site.query.filter_by(is_active=True).order_by(Site.name.asc()).all()
    warehouses = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.name.asc()).all()

    if request.method == "POST":
        priority = (request.form.get("priority") or "NORMAL").strip()
        notes = request.form.get("notes")

        site_id = _to_int(request.form.get("site_id"))
        warehouse_id = _to_int(request.form.get("warehouse_id"))

        article_ids = request.form.getlist("line_article_id[]")
        pending_article_ids = request.form.getlist("line_pending_article_id[]")
        manual_names = request.form.getlist("line_manual_name[]")
        quantities = request.form.getlist("line_quantity[]")
        unit_ids = request.form.getlist("line_unit_id[]")
        line_notes_list = request.form.getlist("line_notes[]")
        urgent_flags = request.form.getlist("line_is_urgent[]")

        max_len = max(
            [
                len(article_ids),
                len(pending_article_ids),
                len(manual_names),
                len(quantities),
                len(unit_ids),
                len(line_notes_list),
            ],
            default=0,
        )

        lines: list[PurchaseRequestLinePayload] = []

        for index in range(max_len):
            article_id_raw = article_ids[index].strip() if index < len(article_ids) else ""
            pending_article_id_raw = pending_article_ids[index].strip() if index < len(pending_article_ids) else ""
            manual_name_raw = manual_names[index].strip() if index < len(manual_names) else ""
            quantity_raw = quantities[index].strip() if index < len(quantities) else ""
            unit_id_raw = unit_ids[index].strip() if index < len(unit_ids) else ""
            line_notes = line_notes_list[index].strip() if index < len(line_notes_list) else None

            if not any([article_id_raw, pending_article_id_raw, manual_name_raw, quantity_raw, unit_id_raw, line_notes]):
                continue

            try:
                quantity_value = Decimal(quantity_raw)
            except (InvalidOperation, TypeError):
                flash(f"La cantidad de la línea {index + 1} no es válida.", "danger")
                return render_template(
                    "purchases/requests/create.html",
                    articles=articles,
                    units=units,
                    sites=sites,
                    warehouses=warehouses,
                    search=search,
                )

            article_id: int | None = None
            pending_article_id: int | None = None

            if manual_name_raw:
                try:
                    pending = create_pending_article(
                        provisional_name=manual_name_raw,
                        description=line_notes,
                        category_id=None,
                        unit_id=int(unit_id_raw) if unit_id_raw else None,
                        requested_by_user_id=current_user.id,
                    )
                    pending_article_id = pending.id
                except PendingArticleServiceError as exc:
                    flash(f"Error en la línea {index + 1}: {str(exc)}", "danger")
                    return render_template(
                        "purchases/requests/create.html",
                        articles=articles,
                        units=units,
                        sites=sites,
                        warehouses=warehouses,
                        search=search,
                    )

            elif article_id_raw:
                article_id = int(article_id_raw)

            elif pending_article_id_raw:
                pending_article_id = int(pending_article_id_raw)

            lines.append(
                PurchaseRequestLinePayload(
                    article_id=article_id,
                    pending_article_id=pending_article_id,
                    quantity_requested=quantity_value,
                    unit_id=int(unit_id_raw) if unit_id_raw else None,
                    line_notes=line_notes,
                    is_urgent=str(index) in urgent_flags,
                )
            )

        try:
            purchase_request = create_purchase_request(
                requested_by_user_id=current_user.id,
                priority=priority,
                notes=notes,
                site_id=site_id,
                warehouse_id=warehouse_id,
                lines=lines,
            )
        except PurchaseRequestServiceError as exc:
            flash(str(exc), "danger")
            return render_template(
                "purchases/requests/create.html",
                articles=articles,
                units=units,
                sites=sites,
                warehouses=warehouses,
                search=search,
            )

        flash("Solicitud de compra creada correctamente.", "success")
        return redirect(url_for("purchases.request_detail", request_id=purchase_request.id))

    return render_template(
        "purchases/requests/create.html",
        articles=articles,
        units=units,
        sites=sites,
        warehouses=warehouses,
        search=search,
    )

@purchases_bp.route("/requests/articles/search")
@login_required
def search_request_articles():
    term = (request.args.get("q") or "").strip()
    warehouse_id = _to_int(request.args.get("warehouse_id"))

    if not warehouse_id:
        return {"items": []}

    if len(term) < 2:
        return {"items": []}

    search_like = f"%{term}%"

    rows = (
        db.session.query(
            Article.id,
            Article.code,
            Article.name,
            Article.unit_id,
            Unit.name.label("unit_name"),
            WarehouseStock.quantity_on_hand,
            WarehouseStock.available_quantity,
        )
        .outerjoin(Unit, Unit.id == Article.unit_id)
        .outerjoin(
            WarehouseStock,
            db.and_(
                WarehouseStock.article_id == Article.id,
                WarehouseStock.warehouse_id == warehouse_id,
            )
        )
        .filter(
            Article.is_active.is_(True),
            db.or_(
                Article.code.ilike(search_like),
                Article.name.ilike(search_like),
            )
        )
        .order_by(Article.code.asc())
        .limit(30)
        .all()
    )

    items = []

    for row in rows:
        quantity_on_hand = Decimal(str(row.quantity_on_hand or 0))
        available_quantity = Decimal(str(row.available_quantity or 0))

        items.append({
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "unit_id": row.unit_id,
            "unit_name": row.unit_name or "",
            "quantity_on_hand": str(quantity_on_hand),
            "available_quantity": str(available_quantity),
        })

    return {"items": items}

@purchases_bp.route("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    purchase_request = get_purchase_request_or_404(request_id)

    return render_template(
        "purchases/requests/detail.html",
        purchase_request=purchase_request,
    )
@purchases_bp.route("/requests/<int:request_id>/send", methods=["POST"])
@login_required
def send_request(request_id: int):
    try:
        purchase_request = submit_purchase_request(request_id=request_id)

    except PurchaseRequestServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.request_detail", request_id=request_id))

    if purchase_request.status == "EN_REVISION_PROVEEDURIA":
        flash("Solicitud enviada directamente a proveeduría correctamente.", "success")
    else:
        flash("Solicitud enviada a jefatura correctamente.", "success")

    return redirect(
        url_for("purchases.request_detail", request_id=purchase_request.id)
    )

@purchases_bp.route("/manager/purchase-requests")
@login_required
def manager_purchase_requests():
    active_site_id = session.get("active_site_id")

    if not active_site_id:
        purchase_requests = []
    else:
        active_site_id = int(active_site_id)

        purchase_requests = (
            PurchaseRequest.query
            .filter(
                db.or_(
                    PurchaseRequest.review_site_id == active_site_id,
                    db.and_(
                        PurchaseRequest.review_site_id.is_(None),
                        PurchaseRequest.site_id == active_site_id,
                        PurchaseRequest.sent_direct_to_procurement.is_(False),
                    ),
                ),
                PurchaseRequest.status == "ENVIADA",
            )
            .order_by(
                PurchaseRequest.created_at.desc(),
                PurchaseRequest.id.desc(),
            )
            .all()
        )

    return render_template(
        "dashboard/manager.html",
        purchase_requests=purchase_requests,
    )

@purchases_bp.route("/dashboard/manager/purchase-request-lines/<int:line_id>/update", methods=["POST"])
@login_required
def manager_update_request_line(line_id: int):
    quantity_raw = request.form.get("quantity_requested")
    cancel_line = request.form.get("cancel_line") == "1"

    line = PurchaseRequestLine.query.get_or_404(line_id)

    try:
        quantity = Decimal(quantity_raw or "0")

        updated_line = update_purchase_request_line_by_manager(
            line_id=line_id,
            quantity_requested=quantity,
            cancel_line=cancel_line,
        )
    except PurchaseRequestServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dashboard.manager_dashboard"))

    flash("Línea actualizada correctamente.", "success")
    return redirect(url_for("dashboard.manager_dashboard"))


@purchases_bp.route("/dashboard/manager/purchase-requests/<int:request_id>/approve", methods=["POST"])
@login_required
def manager_approve_request(request_id: int):
    line_ids = request.form.getlist("line_id[]")
    quantities = request.form.getlist("quantity_requested[]")
    cancelled_lines = set(request.form.getlist("cancel_line[]"))

    review_lines = []

    for index, raw_line_id in enumerate(line_ids):
        line_id = _to_int(raw_line_id)

        if not line_id:
            continue

        quantity_raw = quantities[index] if index < len(quantities) else None

        review_lines.append(
            {
                "line_id": line_id,
                "quantity_requested": quantity_raw,
                "cancel_line": str(line_id) in cancelled_lines,
            }
        )

    try:
        approve_purchase_request_for_quotation(
            request_id=request_id,
            review_lines=review_lines,
        )
    except PurchaseRequestServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dashboard.manager_dashboard"))

    flash("Solicitud aprobada y enviada a proveeduría correctamente.", "success")
    return redirect(url_for("dashboard.manager_dashboard"))
# =========================
# PENDING ARTICLES
# =========================
@purchases_bp.route("/pending-articles")
@login_required
def list_pending_articles_route():
    status = request.args.get("status", type=str)
    search = request.args.get("search", type=str)

    pending_articles = list_pending_articles(status=status, search=search)

    return render_template(
        "purchases/pending_articles/index.html",
        pending_articles=pending_articles,
        selected_status=status,
        search=search,
    )


@purchases_bp.route("/pending-articles/create", methods=["GET", "POST"])
@login_required
def create_pending_article_route():
    categories = ItemCategory.query.order_by(ItemCategory.name.asc()).all()
    units = Unit.query.order_by(Unit.id.asc()).all()

    if request.method == "POST":
        try:
            pending_article = create_pending_article(
                provisional_name=request.form.get("provisional_name"),
                description=request.form.get("description"),
                category_id=_to_int(request.form.get("category_id")),
                unit_id=_to_int(request.form.get("unit_id")),
                requested_by_user_id=current_user.id,
            )
        except PendingArticleServiceError as exc:
            flash(str(exc), "danger")
            return render_template(
                "purchases/pending_articles/create.html",
                categories=categories,
                units=units,
            )

        flash("Artículo pendiente creado correctamente.", "success")
        return redirect(url_for("purchases.pending_article_detail", pending_article_id=pending_article.id))

    return render_template(
        "purchases/pending_articles/create.html",
        categories=categories,
        units=units,
    )


@purchases_bp.route("/pending-articles/<int:pending_article_id>")
@login_required
def pending_article_detail(pending_article_id: int):
    pending_article = get_pending_article_or_404(pending_article_id)

    return render_template(
        "purchases/pending_articles/detail.html",
        pending_article=pending_article,
    )


@purchases_bp.route("/pending-articles/<int:pending_article_id>/resolve", methods=["POST"])
@login_required
def resolve_pending_article_route(pending_article_id: int):
    final_code = (request.form.get("final_code") or "").strip()
    final_name = (request.form.get("final_name") or "").strip()

    if not final_code:
        flash("Debes indicar el código definitivo de 5 dígitos.", "danger")
        return redirect(url_for("purchases.pending_article_detail", pending_article_id=pending_article_id))

    if not final_name:
        flash("Debes indicar el nombre definitivo del artículo.", "danger")
        return redirect(url_for("purchases.pending_article_detail", pending_article_id=pending_article_id))

    try:
        resolve_pending_article(
            pending_article_id=pending_article_id,
            final_code=final_code,
            final_name=final_name,
        )
    except PendingArticleServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.pending_article_detail", pending_article_id=pending_article_id))

    flash("Artículo pendiente resuelto correctamente.", "success")
    return redirect(url_for("purchases.pending_article_detail", pending_article_id=pending_article_id))


# =========================
# COTIZACIONES
# =========================
@purchases_bp.route("/quotations")
@login_required
def list_quotations():
    search = request.args.get("search", type=str)

    quotation_requests = list_quotation_request_groups(search=search)

    return render_template(
        "purchases/quotations/index.html",
        quotation_requests=quotation_requests,
        search=search,
    )

@purchases_bp.route("/quotations/request/<int:request_id>")
@login_required
def quotation_request_lines(request_id: int):
    purchase_request = PurchaseRequest.query.get_or_404(request_id)

    rows = (
        db.session.query(
            PurchaseRequestLine.id.label("purchase_request_line_id"),
            PurchaseRequestLine.line_status.label("line_status"),
            PurchaseRequestLine.quantity_requested.label("quantity_requested"),
            PurchaseRequest.number.label("purchase_request_number"),
            PurchaseRequest.id.label("purchase_request_id"),
            func.count(QuotationLine.id).label("total_quotes"),
            func.sum(
                db.case(
                    (QuotationLine.status == "BORRADOR", 1),
                    else_=0,
                )
            ).label("draft_quotes"),
            func.sum(
                db.case(
                    (QuotationLine.status == "COTIZADA", 1),
                    else_=0,
                )
            ).label("confirmed_quotes"),
            func.max(QuotationLine.quote_date).label("last_quote_date"),
        )
        .join(
            PurchaseRequest,
            PurchaseRequest.id == PurchaseRequestLine.purchase_request_id,
        )
        .outerjoin(
            QuotationLine,
            QuotationLine.purchase_request_line_id == PurchaseRequestLine.id,
        )
        .filter(
            PurchaseRequestLine.purchase_request_id == request_id,
            PurchaseRequestLine.line_status != "CANCELADA",
        )
        .group_by(
            PurchaseRequestLine.id,
            PurchaseRequestLine.line_status,
            PurchaseRequestLine.quantity_requested,
            PurchaseRequest.number,
            PurchaseRequest.id,
        )
        .order_by(PurchaseRequestLine.id.asc())
        .all()
    )

    line_groups = []

    for row in rows:
        request_line = PurchaseRequestLine.query.get(row.purchase_request_line_id)

        line_groups.append({
            "purchase_request_id": row.purchase_request_id,
            "purchase_request_number": row.purchase_request_number,
            "purchase_request_line_id": row.purchase_request_line_id,
            "item_code": request_line.item_code or "-",
            "item_name": request_line.item_name or "Sin artículo",
            "quantity_requested": row.quantity_requested,
            "line_status": row.line_status,
            "total_quotes": int(row.total_quotes or 0),
            "draft_quotes": int(row.draft_quotes or 0),
            "confirmed_quotes": int(row.confirmed_quotes or 0),
            "best_price": None,
            "best_supplier": None,
            "last_quote_date": row.last_quote_date,
        })

    return render_template(
        "purchases/quotations/request_lines.html",
        purchase_request=purchase_request,
        line_groups=line_groups,
    )


@purchases_bp.route("/quotations/create", methods=["GET", "POST"])
@login_required
def create_quotation():
    # 🔥 SOLO solicitudes válidas
    purchase_requests = (
        PurchaseRequest.query.filter(
            PurchaseRequest.status.in_([
                "EN_REVISION_PROVEEDURIA",
                "PARCIALMENTE_COTIZADA",
                "COTIZADA",
            ]))
        .order_by(PurchaseRequest.created_at.desc())
        .all()
    )

    suppliers = (
        Supplier.query.filter_by(is_active=True)
        .order_by(Supplier.commercial_name.asc())
        .all()
    )

    articles = (
        Article.query.filter_by(is_active=True)
        .order_by(Article.code.asc())
        .all()
    )

    pending_articles = (
        PendingArticle.query.filter(
            PendingArticle.status.in_(["PENDIENTE_CODIFICACION", "CODIFICADO"])
        )
        .order_by(PendingArticle.created_at.desc())
        .all()
    )

    # 🔥 MAPA DE LÍNEAS (solo activas)
    purchase_request_lines_map: dict[int, list] = {}
    for pr in purchase_requests:
        purchase_request_lines_map[pr.id] = [
            line for line in pr.lines
            if line.line_status not in ["CANCELADA", "CONVERTIDA_A_OC", "RECIBIDA"]
        ]

    if request.method == "POST":
        purchase_request_id = _to_int(request.form.get("purchase_request_id"))
        quote_date = request.form.get("quote_date")
        notes = request.form.get("notes")

        pr_line_ids = request.form.getlist("line_purchase_request_line_id[]")
        supplier_ids = request.form.getlist("line_supplier_id[]")
        article_ids = request.form.getlist("line_article_id[]")
        pending_article_ids = request.form.getlist("line_pending_article_id[]")
        prices = request.form.getlist("line_unit_price[]")
        currencies = request.form.getlist("line_currency_code[]")
        discounts = request.form.getlist("line_discount_pct[]")
        taxes = request.form.getlist("line_tax_pct[]")
        tax_included_flags = request.form.getlist("line_tax_included[]")
        lead_times = request.form.getlist("line_lead_time_days[]")
        brands = request.form.getlist("line_brand_model[]")
        notes_list = request.form.getlist("line_notes[]")

        # 🔥 NUEVOS CAMPOS
        payment_types = request.form.getlist("line_payment_type[]")
        payment_terms = request.form.getlist("line_payment_term_months[]")
        origin_types = request.form.getlist("line_origin_type[]")

        max_len = max(
            [len(supplier_ids), len(prices)],
            default=0,
        )

        lines: list[QuotationLinePayload] = []

        for index in range(max_len):
            supplier_id = _to_int(supplier_ids[index] if index < len(supplier_ids) else None)
            article_id = _to_int(article_ids[index] if index < len(article_ids) else None)
            pending_article_id = _to_int(
                pending_article_ids[index] if index < len(pending_article_ids) else None
            )
            pr_line_id = _to_int(pr_line_ids[index] if index < len(pr_line_ids) else None)
            price_raw = prices[index] if index < len(prices) else None

            if not any([supplier_id, article_id, pending_article_id, price_raw, pr_line_id]):
                continue

            try:
                unit_price = _to_decimal(price_raw)
                discount_pct = _to_decimal(discounts[index] if index < len(discounts) else None)
                tax_pct = _to_decimal(taxes[index] if index < len(taxes) else None)
            except ValueError:
                flash(f"Error en línea {index + 1}", "danger")
                return render_template(
                    "purchases/quotations/create.html",
                    purchase_requests=purchase_requests,
                    purchase_request_lines_map=purchase_request_lines_map,
                    suppliers=suppliers,
                    articles=articles,
                    pending_articles=pending_articles,
                )

            lines.append(
                QuotationLinePayload(
                    purchase_request_line_id=pr_line_id,
                    supplier_id=supplier_id,
                    quote_date=quote_date,
                    unit_price=unit_price,
                    currency_code=(currencies[index] if index < len(currencies) else "CRC") or "CRC",
                    article_id=article_id,
                    pending_article_id=pending_article_id,
                    discount_pct=discount_pct,
                    tax_pct=tax_pct,
                    tax_included=str(index) in tax_included_flags,
                    lead_time_days=_to_int(lead_times[index] if index < len(lead_times) else None),
                    brand_model=brands[index] if index < len(brands) else None,
                    notes=notes_list[index] if index < len(notes_list) else None,

                    # 🔥 NUEVO
                    payment_type=payment_types[index] if index < len(payment_types) else None,
                    payment_term_months=_to_int(payment_terms[index] if index < len(payment_terms) else None),
                    origin_type=origin_types[index] if index < len(origin_types) else None,

                    status="COTIZADA",
                )
            )

        try:
            quotation_batch = create_quotation_batch(
                purchase_request_id=purchase_request_id,
                created_by_user_id=current_user.id,
                quote_date=quote_date,
                notes=notes,
                lines=lines,
            )
        except QuotationServiceError as exc:
            flash(str(exc), "danger")
            return render_template(
                "purchases/quotations/create.html",
                purchase_requests=purchase_requests,
                purchase_request_lines_map=purchase_request_lines_map,
                suppliers=suppliers,
                articles=articles,
                pending_articles=pending_articles,
            )

        flash("Cotización creada correctamente.", "success")
        return redirect(url_for("purchases.quotation_detail", batch_id=quotation_batch.id))

    return render_template(
        "purchases/quotations/create.html",
        purchase_requests=purchase_requests,
        purchase_request_lines_map=purchase_request_lines_map,
        suppliers=suppliers,
        articles=articles,
        pending_articles=pending_articles,
    )


@purchases_bp.route("/quotations/<int:batch_id>")
@login_required
def quotation_detail(batch_id: int):
    quotation_batch = get_quotation_batch_or_404(batch_id)
    return render_template(
        "purchases/quotations/detail.html",
        quotation_batch=quotation_batch,
    )


# =========================
# ORDENES DE COMPRA
# =========================
@purchases_bp.route("/orders")
@login_required
def list_orders():
    approval_status = request.args.get("approval_status", type=str)
    supplier_id = _to_int(request.args.get("supplier_id"))
    search = request.args.get("search", type=str)

    purchase_orders = list_purchase_orders(
        approval_status=approval_status,
        supplier_id=supplier_id,
        search=search,
    )
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.commercial_name.asc()).all()

    return render_template(
        "purchases/orders/index.html",
        purchase_orders=purchase_orders,
        suppliers=suppliers,
        selected_approval_status=approval_status,
        selected_supplier_id=supplier_id,
        search=search,
    )


@purchases_bp.route("/orders/create", methods=["GET", "POST"])
@login_required
def create_order():
    def _calculate_quote_amounts(line: QuotationLine, quantity: Decimal) -> dict:
        unit_price = Decimal(str(line.unit_price or 0))
        tax_factor = Decimal("1.13")

        if line.tax_included:
            unit_cost_without_tax = unit_price / tax_factor
            subtotal = unit_cost_without_tax * quantity
            total = unit_price * quantity
        else:
            unit_cost_without_tax = unit_price
            subtotal = unit_cost_without_tax * quantity
            total = subtotal * tax_factor

        return {
            "unit_cost_without_tax": unit_cost_without_tax,
            "subtotal": subtotal,
            "tax_amount": total - subtotal,
            "total": total,
        }

    if request.method == "POST":
        q_line_ids = request.form.getlist("line_quotation_line_id[]")
        quantities = request.form.getlist("line_quantity_ordered[]")
        line_notes_list = request.form.getlist("line_notes[]")

        selected_q_line_ids: list[int] = []

        for raw_id in q_line_ids:
            q_line_id = _to_int(raw_id)
            if q_line_id:
                selected_q_line_ids.append(q_line_id)

        if not selected_q_line_ids:
            flash("Debe seleccionar al menos una cotización para crear la OC.", "danger")
            return redirect(url_for("purchases.create_order"))

        quotation_lines = (
            QuotationLine.query
            .filter(QuotationLine.id.in_(selected_q_line_ids))
            .all()
        )

        quotation_by_id = {line.id: line for line in quotation_lines}

        if len(quotation_by_id) != len(set(selected_q_line_ids)):
            flash("Una o más cotizaciones seleccionadas no existen.", "danger")
            return redirect(url_for("purchases.create_order"))

        supplier_id = None
        purchase_request_id = None
        site_id = None
        warehouse_id = None
        currency_code = None
        payment_terms = None

        lines: list[PurchaseOrderLinePayload] = []

        for index, q_line_id in enumerate(selected_q_line_ids):
            quotation_line = quotation_by_id.get(q_line_id)

            if not quotation_line:
                continue

            # 🔥 VALIDACIÓN: la línea de solicitud ya fue usada en otra OC
            if quotation_line.purchase_request_line_id:
                already_used_request_line = PurchaseOrderLine.query.filter(
                    PurchaseOrderLine.purchase_request_line_id == quotation_line.purchase_request_line_id
                ).first()

                if already_used_request_line:
                    flash(
                        f"La línea {index + 1} ya fue utilizada en otra orden de compra.",
                        "danger",
                    )
                    return redirect(url_for("purchases.create_order"))

            is_used = PurchaseOrderLine.query.filter(
                PurchaseOrderLine.quotation_line_id == quotation_line.id
            ).first() is not None

            if is_used:
                flash(
                    f"La cotización de la línea {index + 1} ya fue utilizada en otra OC.",
                    "danger",
                )
                return redirect(url_for("purchases.create_order"))

            if supplier_id is None:
                supplier_id = quotation_line.supplier_id
            elif quotation_line.supplier_id != supplier_id:
                flash("Todas las líneas de una OC deben pertenecer al mismo proveedor.", "danger")
                return redirect(url_for("purchases.create_order"))

            if purchase_request_id is None and quotation_line.purchase_request_line:
                purchase_request_id = quotation_line.purchase_request_line.purchase_request_id

                if quotation_line.purchase_request_line.purchase_request:
                    pr = quotation_line.purchase_request_line.purchase_request
                    site_id = pr.site_id
                    warehouse_id = pr.warehouse_id

            if currency_code is None:
                currency_code = quotation_line.currency_code or "CRC"

            if payment_terms is None:
                if quotation_line.payment_type:
                    if quotation_line.payment_term_months:
                        payment_terms = f"{quotation_line.payment_type} {quotation_line.payment_term_months} meses"
                    else:
                        payment_terms = quotation_line.payment_type

            quantity_raw = quantities[index] if index < len(quantities) else None

            try:
                quantity_ordered = _to_decimal(quantity_raw, default="1")
            except ValueError:
                flash(f"La cantidad de la línea {index + 1} no es válida.", "danger")
                return redirect(url_for("purchases.create_order"))

            if quantity_ordered <= 0:
                flash(f"La cantidad de la línea {index + 1} debe ser mayor a cero.", "danger")
                return redirect(url_for("purchases.create_order"))

            note = line_notes_list[index] if index < len(line_notes_list) else None

            lines.append(
                PurchaseOrderLinePayload(
                    quantity_ordered=quantity_ordered,
                    unit_cost=Decimal("0"),
                    article_id=quotation_line.article_id,
                    pending_article_id=quotation_line.pending_article_id,
                    purchase_request_line_id=quotation_line.purchase_request_line_id,
                    quotation_line_id=quotation_line.id,
                    unit_id=(
                        quotation_line.article.unit_id
                        if quotation_line.article and quotation_line.article.unit_id
                        else quotation_line.purchase_request_line.unit_id
                        if quotation_line.purchase_request_line and quotation_line.purchase_request_line.unit_id
                        else None
                    ),
                    discount_pct=quotation_line.discount_pct or Decimal("0"),
                    tax_pct=Decimal("13"),
                    line_subtotal=Decimal("0"),
                    line_total=Decimal("0"),
                    line_notes=note or quotation_line.notes,
                )
            )

        try:
            purchase_order = create_purchase_order(
                supplier_id=supplier_id,
                generated_by_user_id=current_user.id,
                purchase_request_id=purchase_request_id,
                site_id=site_id,
                warehouse_id=warehouse_id,
                payment_terms=payment_terms,
                currency_code=currency_code or "CRC",
                notes=request.form.get("notes"),
                lines=lines,
            )
        except PurchaseOrderServiceError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("purchases.create_order"))

        flash("Orden de compra creada correctamente y enviada a aprobación.", "success")
        return redirect(url_for("purchases.order_print", order_id=purchase_order.id))

    used_quotation_line_ids = {
        row[0]
        for row in (
            db.session.query(PurchaseOrderLine.quotation_line_id)
            .filter(PurchaseOrderLine.quotation_line_id.isnot(None))
            .all()
        )
    }

    used_purchase_request_line_ids = {
        row[0]
        for row in (
            db.session.query(PurchaseOrderLine.purchase_request_line_id)
            .filter(PurchaseOrderLine.purchase_request_line_id.isnot(None))
            .all()
        )
    }

    quotation_lines = (
        QuotationLine.query
        .filter(QuotationLine.status == "COTIZADA")
        .order_by(
            QuotationLine.purchase_request_line_id.asc(),
            QuotationLine.quote_date.desc(),
            QuotationLine.id.desc(),
        )
        .all()
    )

    quotation_groups_map: dict[str, dict] = {}

    for line in quotation_lines:

        if line.purchase_request_line_id and line.purchase_request_line_id in used_purchase_request_line_ids:
            continue

        if line.id in used_quotation_line_ids:
            continue

        quantity = Decimal("1")

        if line.purchase_request_line and line.purchase_request_line.quantity_requested:
            quantity = Decimal(str(line.purchase_request_line.quantity_requested))

        amounts = _calculate_quote_amounts(line, quantity)

        if line.purchase_request_line_id:
            group_key = f"pr-line-{line.purchase_request_line_id}"
        else:
            group_key = f"quotation-line-{line.id}"

        if group_key not in quotation_groups_map:
            purchase_request = (
                line.purchase_request_line.purchase_request
                if line.purchase_request_line and line.purchase_request_line.purchase_request
                else None
            )

            quotation_groups_map[group_key] = {
                "key": group_key,
                "purchase_request_line_id": line.purchase_request_line_id,
                "purchase_request_number": purchase_request.number if purchase_request else "-",
                "item_code": line.item_code or "",
                "item_name": line.item_name or "Sin artículo",
                "quantity_requested": str(quantity),
                "unit_name": (
                    line.purchase_request_line.unit.name
                    if line.purchase_request_line
                    and line.purchase_request_line.unit
                    else line.article.unit.name
                    if line.article and line.article.unit
                    else "-"
                ),
                "options": [],
            }

        quotation_groups_map[group_key]["options"].append(
            {
                "quotation_line_id": line.id,
                "supplier_id": line.supplier_id,
                "supplier_name": line.supplier.commercial_name if line.supplier else "-",
                "unit_price": str(line.unit_price or 0),
                "currency_code": line.currency_code or "CRC",
                "discount_pct": str(line.discount_pct or 0),
                "tax_pct": str(line.tax_pct or 0),
                "tax_included": bool(line.tax_included),
                "quote_date": line.quote_date.strftime("%d/%m/%Y") if line.quote_date else "-",
                "payment_type": line.payment_type or "",
                "payment_term_months": line.payment_term_months or "",
                "origin_type": line.origin_type or "",
                "brand_model": line.brand_model or "",
                "notes": line.notes or "",
                "estimated_subtotal": str(amounts["subtotal"]),
                "estimated_tax": str(amounts["tax_amount"]),
                "estimated_total": str(amounts["total"]),
            }
        )

    quotation_groups = list(quotation_groups_map.values())

    quotation_groups.sort(
        key=lambda item: (
            item["purchase_request_number"] or "",
            item["item_name"] or "",
        )
    )

    return render_template(
        "purchases/orders/create.html",
        quotation_groups=quotation_groups,
    )

@purchases_bp.route("/orders/create/manual", methods=["GET", "POST"])
@login_required
def create_order_manual():
    flash(
        "Módulo manual pendiente de separar. Por ahora use la creación desde cotización.",
        "warning",
    )
    return redirect(url_for("purchases.create_order"))

@purchases_bp.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id: int):
    purchase_order = get_purchase_order_or_404(order_id)
    return render_template(
        "purchases/orders/detail.html",
        purchase_order=purchase_order,
        cr_datetime=_cr_datetime,
    )


@purchases_bp.route("/orders/<int:order_id>/print")
@login_required
def order_print(order_id: int):
    purchase_order = get_purchase_order_or_404(order_id)
    return render_template(
        "purchases/orders/print.html",
        purchase_order=purchase_order,
        cr_datetime=_cr_datetime,
    )


@purchases_bp.route("/orders/<int:order_id>/approve", methods=["POST"])
@login_required
def approve_order(order_id: int):
    try:
        register_purchase_order_approval(
            purchase_order_id=order_id,
            approved_by_user_id=current_user.id,
            status="APROBADA",
            reason=request.form.get("reason"),
        )
    except PurchaseOrderServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.order_detail", order_id=order_id))

    flash("Orden de compra aprobada.", "success")
    return redirect(url_for("purchases.order_detail", order_id=order_id))


@purchases_bp.route("/orders/<int:order_id>/reject", methods=["POST"])
@login_required
def reject_order(order_id: int):
    try:
        register_purchase_order_approval(
            purchase_order_id=order_id,
            approved_by_user_id=current_user.id,
            status="RECHAZADA",
            reason=request.form.get("reason"),
        )
    except PurchaseOrderServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.order_detail", order_id=order_id))

    flash("Orden de compra rechazada.", "warning")
    return redirect(url_for("purchases.order_detail", order_id=order_id))


# =========================
# ENTRADAS A INVENTARIO
# =========================
@purchases_bp.route("/inventory-entries")
@login_required
def list_entries():
    search = request.args.get("search", type=str)
    inventory_entries = list_inventory_entries(search=search)

    return render_template(
        "purchases/inventory_entries/index.html",
        inventory_entries=inventory_entries,
        search=search,
    )


@purchases_bp.route("/entries/create", methods=["GET", "POST"])
@login_required
def create_entry():
    purchase_orders = _get_valid_purchase_orders_for_receiving()

    suppliers = (
        Supplier.query.filter_by(is_active=True)
        .order_by(Supplier.commercial_name.asc())
        .all()
    )

    warehouses = (
        Warehouse.query.filter_by(is_active=True)
        .order_by(Warehouse.name.asc())
        .all()
    )

    units = Unit.query.order_by(Unit.id.asc()).all()

    articles = (
        Article.query.filter_by(is_active=True)
        .order_by(Article.code.asc())
        .all()
    )

    pending_articles = (
        PendingArticle.query.filter(
            PendingArticle.status.in_(["PENDIENTE_CODIFICACION", "CODIFICADO"])
        )
        .order_by(PendingArticle.created_at.desc())
        .all()
    )

    purchase_order_lines_map: dict[int, list] = {}
    for po in purchase_orders:
        purchase_order_lines_map[po.id] = list(po.lines) if po.lines else []

    warehouse_locations_map: dict[int, list] = {}
    for wh in warehouses:
        warehouse_locations_map[wh.id] = list(wh.locations) if wh.locations else []

    if request.method == "POST":
        purchase_order_id = _to_int(request.form.get("purchase_order_id"))
        supplier_id = _to_int(request.form.get("supplier_id"))
        warehouse_id = _to_int(request.form.get("warehouse_id"))
        invoice_number = request.form.get("invoice_number")
        invoice_date = request.form.get("invoice_date")
        notes = request.form.get("notes")

        po_line_ids = request.form.getlist("line_purchase_order_line_id[]")
        location_ids = request.form.getlist("line_warehouse_location_id[]")
        article_ids = request.form.getlist("line_article_id[]")
        pending_ids = request.form.getlist("line_pending_article_id[]")
        quantities = request.form.getlist("line_quantity_received[]")
        unit_ids = request.form.getlist("line_unit_id[]")
        cost_wo_tax = request.form.getlist("line_unit_cost_without_tax[]")
        cost_w_tax = request.form.getlist("line_unit_cost_with_tax[]")
        discounts = request.form.getlist("line_discount_pct[]")
        taxes = request.form.getlist("line_tax_pct[]")
        line_notes_list = request.form.getlist("line_notes[]")

        max_len = max(
            [
                len(article_ids),
                len(pending_ids),
                len(quantities),
            ],
            default=0,
        )

        lines: list[InventoryEntryLinePayload] = []

        for i in range(max_len):
            quantity_raw = quantities[i] if i < len(quantities) else None
            article_id = _to_int(article_ids[i] if i < len(article_ids) else None)
            pending_id = _to_int(pending_ids[i] if i < len(pending_ids) else None)
            po_line_id = _to_int(po_line_ids[i] if i < len(po_line_ids) else None)

            if not any([quantity_raw, article_id, pending_id, po_line_id]):
                continue

            try:
                quantity = _to_decimal(quantity_raw)
                cost1 = _to_decimal(cost_wo_tax[i] if i < len(cost_wo_tax) else None)
                cost2 = _to_decimal(cost_w_tax[i] if i < len(cost_w_tax) else None)
                discount = _to_decimal(discounts[i] if i < len(discounts) else None)
                tax = _to_decimal(taxes[i] if i < len(taxes) else None)
            except ValueError:
                flash(f"Error en línea {i+1}", "danger")
                return render_template(
                    "purchases/inventory_entries/create.html",
                    purchase_orders=purchase_orders,
                    purchase_order_lines_map=purchase_order_lines_map,
                    suppliers=suppliers,
                    warehouses=warehouses,
                    warehouse_locations_map=warehouse_locations_map,
                    units=units,
                    articles=articles,
                    pending_articles=pending_articles,
                )

            lines.append(
                InventoryEntryLinePayload(
                    purchase_order_line_id=po_line_id,
                    article_id=article_id,
                    pending_article_id=pending_id,
                    warehouse_location_id=_to_int(
                        location_ids[i] if i < len(location_ids) else None
                    ),
                    quantity_received=quantity,
                    unit_id=_to_int(unit_ids[i] if i < len(unit_ids) else None),
                    unit_cost_without_tax=cost1,
                    unit_cost_with_tax=cost2,
                    discount_pct=discount,
                    tax_pct=tax,
                    line_notes=line_notes_list[i] if i < len(line_notes_list) else None,
                )
            )

        try:
            entry = create_inventory_entry(
                purchase_order_id=purchase_order_id,
                supplier_id=supplier_id,
                warehouse_id=warehouse_id,
                entered_by_user_id=current_user.id,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                notes=notes,
                lines=lines,
            )
        except InventoryEntryServiceError as exc:
            flash(str(exc), "danger")
            return render_template(
                "purchases/inventory_entries/create.html",
                purchase_orders=purchase_orders,
                purchase_order_lines_map=purchase_order_lines_map,
                suppliers=suppliers,
                warehouses=warehouses,
                warehouse_locations_map=warehouse_locations_map,
                units=units,
                articles=articles,
                pending_articles=pending_articles,
            )

        flash("Entrada registrada correctamente.", "success")
        return redirect(url_for("purchases.entry_detail", entry_id=entry.id))

    return render_template(
        "purchases/inventory_entries/create.html",
        purchase_orders=purchase_orders,
        purchase_order_lines_map=purchase_order_lines_map,
        suppliers=suppliers,
        warehouses=warehouses,
        warehouse_locations_map=warehouse_locations_map,
        units=units,
        articles=articles,
        pending_articles=pending_articles,
    )


@purchases_bp.route("/inventory-entries/<int:entry_id>")
@login_required
def entry_detail(entry_id: int):
    inventory_entry = get_inventory_entry_or_404(entry_id)
    return render_template(
        "purchases/inventory_entries/detail.html",
        inventory_entry=inventory_entry,
    )

@purchases_bp.route("/quotations/line/<int:line_id>")
@login_required
def quotation_line_view(line_id: int):
    request_line = PurchaseRequestLine.query.get_or_404(line_id)

    try:
        comparison = get_comparison_for_purchase_request_line(
            purchase_request_line_id=line_id
        )
    except QuotationServiceError as exc:
        flash(str(exc), "danger")

        if request_line.purchase_request_id:
            return redirect(
                url_for(
                    "purchases.quotation_request_lines",
                    request_id=request_line.purchase_request_id,
                )
            )

        return redirect(url_for("purchases.list_quotations"))

    article_id = request_line.article_id

    suppliers = []

    if article_id:
        supplier_ids = [
            row.supplier_id
            for row in (
                ArticleSupplier.query
                .filter(
                    ArticleSupplier.article_id == article_id,
                    ArticleSupplier.is_active.is_(True),
                )
                .all()
            )
        ]

        if supplier_ids:
            suppliers = (
                Supplier.query
                .filter(
                    Supplier.id.in_(supplier_ids),
                    Supplier.is_active.is_(True),
                )
                .order_by(
                    Supplier.commercial_name.asc(),
                    Supplier.legal_name.asc(),
                )
                .all()
            )

    return render_template(
        "purchases/quotations/line.html",
        line_id=line_id,
        request_line=request_line,
        comparison=comparison,
        suppliers=suppliers,
    )

@purchases_bp.route("/quotations/line/<int:line_id>/quote", methods=["POST"])
@login_required
def create_quote_for_line(line_id: int):
    supplier_id = _to_int(request.form.get("supplier_id"))
    new_supplier_name = request.form.get("new_supplier_name")

    if supplier_id == -1:
        supplier_id = None
    else:
        new_supplier_name = None

    unit_price = request.form.get("unit_price")
    use_last_price = request.form.get("use_last_price") == "1"

    discount_pct = request.form.get("discount_pct") or "0"
    tax_pct = request.form.get("tax_pct") or "13"
    tax_included = request.form.get("tax_included") == "1"

    payment_type = request.form.get("payment_type") or None
    payment_term = _to_int(request.form.get("payment_term_months"))
    origin_type = request.form.get("origin_type") or None

    lead_time_days = _to_int(request.form.get("lead_time_days"))
    brand_model = request.form.get("brand_model")
    notes = request.form.get("notes")
    status = request.form.get("status") or "COTIZADA"

    try:
        create_single_line_quotation(
            purchase_request_line_id=line_id,
            supplier_id=supplier_id,
            new_supplier_name=new_supplier_name,
            created_by_user_id=current_user.id,
            unit_price=unit_price,
            use_last_price=use_last_price,
            discount_pct=discount_pct,
            tax_pct=tax_pct,
            tax_included=tax_included,
            payment_type=payment_type,
            payment_term_months=payment_term,
            origin_type=origin_type,
            lead_time_days=lead_time_days,
            brand_model=brand_model,
            notes=notes,
            status=status,
        )
    except QuotationServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.quotation_line_view", line_id=line_id))

    flash("Cotización guardada correctamente.", "success")
    request_line = PurchaseRequestLine.query.get(line_id)

    return redirect(
        url_for(
            "purchases.quotation_request_lines",
            request_id=request_line.purchase_request_id,
        )
    )

@purchases_bp.route("/quotations/last-price")
@login_required
def get_last_price():
    supplier_id = _to_int(request.args.get("supplier_id"))
    article_id = _to_int(request.args.get("article_id"))
    pending_article_id = _to_int(request.args.get("pending_article_id"))

    try:
        last = get_last_price_for_supplier(
            supplier_id=supplier_id,
            article_id=article_id,
            pending_article_id=pending_article_id,
        )
    except QuotationServiceError as exc:
        return {"error": str(exc)}, 400

    if not last:
        return {"price": None}

    return {
        "price": str(last.unit_price),
        "date": str(last.quote_date),
    }

@purchases_bp.route("/quotations/line/<int:line_id>/export-excel")
@login_required
def export_quotation_comparison_excel(line_id: int):
    try:
        comparison = get_comparison_for_purchase_request_line(
            purchase_request_line_id=line_id
        )
    except QuotationServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.create_quotation"))

    request_line = PurchaseRequestLine.query.get_or_404(line_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Comparativo"

    title = "Comparativo de Cotizaciones"
    ws.merge_cells("A1:L1")
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=16)
    ws["A1"].alignment = Alignment(horizontal="center")

    ws["A3"] = "Artículo:"
    ws["B3"] = request_line.item_name or "Sin artículo"
    ws["A4"] = "Código:"
    ws["B4"] = request_line.item_code or "-"
    ws["A5"] = "Cantidad:"
    ws["B5"] = request_line.quantity_requested

    headers = [
        "#",
        "Proveedor",
        "Monto ingresado",
        "Tipo IVA",
        "Subtotal",
        "Descuento %",
        "Monto descuento",
        "IVA %",
        "Monto IVA",
        "Total",
        "Fecha",
        "Pago",
    ]

    start_row = 7

    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F2937")
        cell.alignment = Alignment(horizontal="center")

    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for index, item in enumerate(comparison, start=1):
        row = start_row + index

        values = [
            "MEJOR" if item.get("is_best_price") else item.get("rank"),
            item.get("supplier_name"),
            float(item.get("last_price") or 0),
            "Con IVA" if item.get("tax_included") else "Sin IVA",
            float(item.get("subtotal") or 0),
            float(item.get("discount_pct") or 0),
            float(item.get("discount_amount") or 0),
            float(item.get("tax_pct") or 0),
            float(item.get("tax_amount") or 0),
            float(item.get("total_amount") or 0),
            item.get("last_quote_date").strftime("%d/%m/%Y") if item.get("last_quote_date") else "-",
            (
                f"{item.get('payment_type')} / {item.get('payment_term_months')} meses"
                if item.get("payment_type") and item.get("payment_term_months")
                else item.get("payment_type") or "-"
            ),
        ]

        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = border
            cell.alignment = Alignment(vertical="center")

            if col in [3, 5, 7, 9, 10]:
                cell.number_format = '#,##0.00'

            if col in [6, 8]:
                cell.number_format = '0.00'

            if item.get("is_best_price"):
                cell.fill = PatternFill("solid", fgColor="DCFCE7")

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 22

    ws.freeze_panes = "A8"

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"comparativo_cotizacion_linea_{line_id}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@purchases_bp.route("/quotations/line/<int:line_id>/print")
@login_required
def print_quotation_comparison(line_id: int):
    try:
        comparison = get_comparison_for_purchase_request_line(
            purchase_request_line_id=line_id
        )
    except QuotationServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.create_quotation"))

    request_line = PurchaseRequestLine.query.get_or_404(line_id)

    return render_template(
        "purchases/quotations/print_comparison.html",
        request_line=request_line,
        comparison=comparison,
        generated_at=datetime.now(CR_TZ),
    )

@purchases_bp.route("/orders/<int:order_id>/upload-approved-pdf", methods=["POST"])
@login_required
def upload_approved_pdf(order_id):
    file = request.files.get("file")

    if not file or not file.filename:
        flash("Debe subir un archivo PDF.", "danger")
        return redirect(url_for("purchases.order_detail", order_id=order_id))

    if not file.filename.lower().endswith(".pdf"):
        flash("El archivo debe ser PDF.", "danger")
        return redirect(url_for("purchases.order_detail", order_id=order_id))

    order = PurchaseOrder.query.get_or_404(order_id)

    file_data = file.read()

    if not file_data:
        flash("El archivo PDF está vacío.", "danger")
        return redirect(url_for("purchases.order_detail", order_id=order_id))

    approval = PurchaseOrderApproval(
        purchase_order_id=order_id,
        approved_by_user_id=current_user.id,
        status="APROBADA",
        reason="OC firmada y adjuntada en PDF.",
        approved_pdf_data=file_data,
        approved_pdf_mime_type=file.mimetype or "application/pdf",
        approved_pdf_original_name=file.filename,
        approved_pdf_uploaded_at=datetime.now(UTC),
    )

    order.approval_status = "APROBADA"
    order.approved_at = datetime.now(UTC)

    db.session.add(approval)
    db.session.commit()

    flash("Orden aprobada correctamente con PDF firmado.", "success")
    return redirect(url_for("purchases.order_detail", order_id=order_id))


@purchases_bp.route("/orders/<int:order_id>/approved-pdf")
@login_required
def view_approved_pdf(order_id):
    approval = (
        PurchaseOrderApproval.query
        .filter(
            PurchaseOrderApproval.purchase_order_id == order_id,
            PurchaseOrderApproval.status == "APROBADA",
            PurchaseOrderApproval.approved_pdf_data.isnot(None),
        )
        .order_by(PurchaseOrderApproval.created_at.desc())
        .first()
    )

    if not approval:
        flash("No hay PDF aprobado para esta orden.", "warning")
        return redirect(url_for("purchases.order_detail", order_id=order_id))

    filename = approval.approved_pdf_original_name or f"OC_{order_id}.pdf"

    return Response(
        approval.approved_pdf_data,
        mimetype=approval.approved_pdf_mime_type or "application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"'
        },
    )

@purchases_bp.route(
    "/orders/lines/<int:line_id>/adjust",
    methods=["POST"],
)
@login_required
def adjust_purchase_order_line(line_id: int):

    quantity = request.form.get("quantity_ordered")
    unit_cost = request.form.get("unit_cost")

    try:

        adjusted_line = adjust_approved_purchase_order_line(
            purchase_order_line_id=line_id,
            new_quantity=quantity,
            new_unit_cost=unit_cost,
        )

    except PurchaseOrderServiceError as exc:

        flash(str(exc), "danger")

        return redirect(
            url_for(
                "purchases.order_detail",
                order_id=PurchaseOrderLine.query.get_or_404(line_id).purchase_order_id,
            )
        )

    flash(
        "Línea de orden ajustada correctamente.",
        "success",
    )

    return redirect(
        url_for(
            "purchases.order_detail",
            order_id=adjusted_line.purchase_order_id,
        )
    )