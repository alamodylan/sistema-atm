from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
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
)
from app.services.purchase_request_service import (
    PurchaseRequestLinePayload,
    PurchaseRequestServiceError,
    create_purchase_request,
    get_purchase_request_or_404,
    list_purchase_requests,
)
from app.services.quotation_service import (
    QuotationLinePayload,
    QuotationServiceError,
    create_quotation_batch,
    get_quotation_batch_or_404,
    list_quotation_batches,
)

purchases_bp = Blueprint("purchases", __name__, template_folder="../templates")


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

    purchase_requests = list_purchase_requests(
        status=status,
        priority=priority,
        search=search,
    )

    return render_template(
        "purchases/requests/index.html",
        purchase_requests=purchase_requests,
        selected_status=status,
        selected_priority=priority,
        search=search,
    )


@purchases_bp.route("/requests/create", methods=["GET", "POST"])
@login_required
def create_request():
    articles = Article.query.filter_by(is_active=True).order_by(Article.code.asc()).all()
    pending_articles = PendingArticle.query.order_by(PendingArticle.created_at.desc()).all()
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
        quantities = request.form.getlist("line_quantity[]")
        unit_ids = request.form.getlist("line_unit_id[]")
        line_notes_list = request.form.getlist("line_notes[]")
        urgent_flags = request.form.getlist("line_is_urgent[]")

        max_len = max(
            len(article_ids),
            len(pending_article_ids),
            len(quantities),
            len(unit_ids),
            len(line_notes_list),
            default=0,
        )

        lines: list[PurchaseRequestLinePayload] = []

        for index in range(max_len):
            article_id_raw = article_ids[index].strip() if index < len(article_ids) else ""
            pending_article_id_raw = pending_article_ids[index].strip() if index < len(pending_article_ids) else ""
            quantity_raw = quantities[index].strip() if index < len(quantities) else ""
            unit_id_raw = unit_ids[index].strip() if index < len(unit_ids) else ""
            line_notes = line_notes_list[index].strip() if index < len(line_notes_list) else None

            if not any([article_id_raw, pending_article_id_raw, quantity_raw, unit_id_raw, line_notes]):
                continue

            try:
                quantity_value = Decimal(quantity_raw)
            except (InvalidOperation, TypeError):
                flash(f"La cantidad de la línea {index + 1} no es válida.", "danger")
                return render_template(
                    "purchases/requests/create.html",
                    articles=articles,
                    pending_articles=pending_articles,
                    units=units,
                    sites=sites,
                    warehouses=warehouses,
                )

            lines.append(
                PurchaseRequestLinePayload(
                    article_id=int(article_id_raw) if article_id_raw else None,
                    pending_article_id=int(pending_article_id_raw) if pending_article_id_raw else None,
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
                pending_articles=pending_articles,
                units=units,
                sites=sites,
                warehouses=warehouses,
            )

        flash("Solicitud de compra creada correctamente.", "success")
        return redirect(url_for("purchases.request_detail", request_id=purchase_request.id))

    return render_template(
        "purchases/requests/create.html",
        articles=articles,
        pending_articles=pending_articles,
        units=units,
        sites=sites,
        warehouses=warehouses,
    )


@purchases_bp.route("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    purchase_request = get_purchase_request_or_404(request_id)
    return render_template(
        "purchases/requests/detail.html",
        purchase_request=purchase_request,
    )


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
    articles = Article.query.filter_by(is_active=True).order_by(Article.code.asc()).all()

    return render_template(
        "purchases/pending_articles/detail.html",
        pending_article=pending_article,
        articles=articles,
    )


@purchases_bp.route("/pending-articles/<int:pending_article_id>/resolve", methods=["POST"])
@login_required
def resolve_pending_article_route(pending_article_id: int):
    linked_article_id = _to_int(request.form.get("linked_article_id"))

    if not linked_article_id:
        flash("Debes seleccionar el artículo definitivo.", "danger")
        return redirect(url_for("purchases.pending_article_detail", pending_article_id=pending_article_id))

    try:
        resolve_pending_article(
            pending_article_id=pending_article_id,
            linked_article_id=linked_article_id,
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
    quotation_batches = list_quotation_batches(search=search)

    return render_template(
        "purchases/quotations/index.html",
        quotation_batches=quotation_batches,
        search=search,
    )


@purchases_bp.route("/quotations/create", methods=["GET", "POST"])
@login_required
def create_quotation():
    purchase_requests = (
        PurchaseRequest.query.order_by(PurchaseRequest.created_at.desc()).all()
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

    # Mapa simple para mostrar líneas de solicitud en la vista
    purchase_request_lines_map: dict[int, list] = {}
    for pr in purchase_requests:
        purchase_request_lines_map[pr.id] = list(pr.lines) if pr.lines else []

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

        max_len = max(
            len(supplier_ids),
            len(article_ids),
            len(pending_article_ids),
            len(prices),
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
                discount_pct = _to_decimal(
                    discounts[index] if index < len(discounts) else None
                )
                tax_pct = _to_decimal(
                    taxes[index] if index < len(taxes) else None
                )
            except ValueError:
                flash(
                    f"Hay valores inválidos en la línea {index + 1} de cotización.",
                    "danger",
                )
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
                    lead_time_days=_to_int(
                        lead_times[index] if index < len(lead_times) else None
                    ),
                    brand_model=brands[index] if index < len(brands) else None,
                    notes=notes_list[index] if index < len(notes_list) else None,
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
        return redirect(
            url_for("purchases.quotation_detail", batch_id=quotation_batch.id)
        )

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
    purchase_requests = (
        PurchaseRequest.query.order_by(PurchaseRequest.created_at.desc()).all()
    )
    suppliers = (
        Supplier.query.filter_by(is_active=True)
        .order_by(Supplier.commercial_name.asc())
        .all()
    )
    sites = Site.query.filter_by(is_active=True).order_by(Site.name.asc()).all()
    warehouses = (
        Warehouse.query.filter_by(is_active=True)
        .order_by(Warehouse.name.asc())
        .all()
    )
    quotation_batches = (
        QuotationBatch.query.order_by(QuotationBatch.created_at.desc()).all()
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

    # Mapa de líneas por solicitud
    purchase_request_lines_map: dict[int, list] = {}
    for pr in purchase_requests:
        purchase_request_lines_map[pr.id] = list(pr.lines) if pr.lines else []

    # Mapa de líneas por lote de cotización
    quotation_lines_map: dict[int, list] = {}
    for batch in quotation_batches:
        quotation_lines_map[batch.id] = list(batch.lines) if batch.lines else []

    if request.method == "POST":
        supplier_id = _to_int(request.form.get("supplier_id"))
        purchase_request_id = _to_int(request.form.get("purchase_request_id"))
        site_id = _to_int(request.form.get("site_id"))
        warehouse_id = _to_int(request.form.get("warehouse_id"))
        payment_terms = request.form.get("payment_terms")
        currency_code = request.form.get("currency_code") or "CRC"
        notes = request.form.get("notes")

        pr_line_ids = request.form.getlist("line_purchase_request_line_id[]")
        q_line_ids = request.form.getlist("line_quotation_line_id[]")
        article_ids = request.form.getlist("line_article_id[]")
        pending_article_ids = request.form.getlist("line_pending_article_id[]")
        quantities = request.form.getlist("line_quantity_ordered[]")
        unit_ids = request.form.getlist("line_unit_id[]")
        unit_costs = request.form.getlist("line_unit_cost[]")
        discounts = request.form.getlist("line_discount_pct[]")
        taxes = request.form.getlist("line_tax_pct[]")
        subtotals = request.form.getlist("line_subtotal[]")
        totals = request.form.getlist("line_total[]")
        line_notes_list = request.form.getlist("line_notes[]")

        max_len = max(
            len(quantities),
            len(article_ids),
            len(pending_article_ids),
            len(pr_line_ids),
            len(q_line_ids),
            default=0,
        )

        lines: list[PurchaseOrderLinePayload] = []

        for index in range(max_len):
            quantity_raw = quantities[index] if index < len(quantities) else None
            article_id = _to_int(article_ids[index] if index < len(article_ids) else None)
            pending_article_id = _to_int(
                pending_article_ids[index] if index < len(pending_article_ids) else None
            )
            pr_line_id = _to_int(pr_line_ids[index] if index < len(pr_line_ids) else None)
            q_line_id = _to_int(q_line_ids[index] if index < len(q_line_ids) else None)

            if not any([quantity_raw, article_id, pending_article_id, pr_line_id, q_line_id]):
                continue

            try:
                quantity_ordered = _to_decimal(quantity_raw)
                unit_cost = _to_decimal(
                    unit_costs[index] if index < len(unit_costs) else None
                )
                discount_pct = _to_decimal(
                    discounts[index] if index < len(discounts) else None
                )
                tax_pct = _to_decimal(
                    taxes[index] if index < len(taxes) else None
                )
                line_subtotal = _to_decimal(
                    subtotals[index] if index < len(subtotals) else None
                )
                line_total = _to_decimal(
                    totals[index] if index < len(totals) else None
                )
            except ValueError:
                flash(f"Hay valores inválidos en la línea {index + 1} de la orden.", "danger")
                return render_template(
                    "purchases/orders/create.html",
                    purchase_requests=purchase_requests,
                    purchase_request_lines_map=purchase_request_lines_map,
                    suppliers=suppliers,
                    sites=sites,
                    warehouses=warehouses,
                    quotation_batches=quotation_batches,
                    quotation_lines_map=quotation_lines_map,
                    units=units,
                    articles=articles,
                    pending_articles=pending_articles,
                )

            lines.append(
                PurchaseOrderLinePayload(
                    quantity_ordered=quantity_ordered,
                    unit_cost=unit_cost,
                    article_id=article_id,
                    pending_article_id=pending_article_id,
                    purchase_request_line_id=pr_line_id,
                    quotation_line_id=q_line_id,
                    unit_id=_to_int(unit_ids[index] if index < len(unit_ids) else None),
                    discount_pct=discount_pct,
                    tax_pct=tax_pct,
                    line_subtotal=line_subtotal,
                    line_total=line_total,
                    line_notes=line_notes_list[index] if index < len(line_notes_list) else None,
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
                currency_code=currency_code,
                notes=notes,
                lines=lines,
            )
        except PurchaseOrderServiceError as exc:
            flash(str(exc), "danger")
            return render_template(
                "purchases/orders/create.html",
                purchase_requests=purchase_requests,
                purchase_request_lines_map=purchase_request_lines_map,
                suppliers=suppliers,
                sites=sites,
                warehouses=warehouses,
                quotation_batches=quotation_batches,
                quotation_lines_map=quotation_lines_map,
                units=units,
                articles=articles,
                pending_articles=pending_articles,
            )

        flash("Orden de compra creada correctamente.", "success")
        return redirect(url_for("purchases.order_detail", order_id=purchase_order.id))

    return render_template(
        "purchases/orders/create.html",
        purchase_requests=purchase_requests,
        purchase_request_lines_map=purchase_request_lines_map,
        suppliers=suppliers,
        sites=sites,
        warehouses=warehouses,
        quotation_batches=quotation_batches,
        quotation_lines_map=quotation_lines_map,
        units=units,
        articles=articles,
        pending_articles=pending_articles,
    )


@purchases_bp.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id: int):
    purchase_order = get_purchase_order_or_404(order_id)
    return render_template(
        "purchases/orders/detail.html",
        purchase_order=purchase_order,
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

    # SOLO pendientes utilizables (ya codificados)
    pending_articles = (
        PendingArticle.query.filter(
            PendingArticle.status == "CODIFICADO"
        )
        .order_by(PendingArticle.created_at.desc())
        .all()
    )

    # =========================
    # MAPAS PARA UI INTELIGENTE
    # =========================

    purchase_order_lines_map: dict[int, list] = {}
    for po in purchase_orders:
        purchase_order_lines_map[po.id] = list(po.lines) if po.lines else []

    warehouse_locations_map: dict[int, list] = {}
    for wh in warehouses:
        warehouse_locations_map[wh.id] = list(wh.locations) if wh.locations else []

    # =========================
    # POST
    # =========================

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

        max_len = max(len(quantities), len(article_ids), len(pending_ids), default=0)

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