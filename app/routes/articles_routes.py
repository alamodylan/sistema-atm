#routes/ inventory_routes.py
from flask import Blueprint, flash, render_template, request
from flask_login import login_required

from app.models.article import Article
from app.models.inventory import InventoryLedger, WarehouseStock
from app.models.warehouse import Warehouse
from app.services.inventory_service import (
    InventoryServiceError,
    get_article_stock_summary,
)

articles_bp = Blueprint("articles", __name__)


# =========================================================
# INVENTARIO - PANTALLA PRINCIPAL
# =========================================================
@articles_bp.route("/", methods=["GET"])
@login_required
def inventory_home():
    query = (
        db_query_articles()
        .order_by(Article.name.asc())
        .limit(100)
        .all()
    )

    return render_template(
        "articles/index.html",
        title="Artículos",
        subtitle="Consulta global de artículos y distribución en bodegas.",
        articles=query,
    )


# =========================================================
# BÚSQUEDA DE ARTÍCULOS
# =========================================================
@articles_bp.route("/articles/search", methods=["GET"])
@login_required
def search_articles():
    q = (request.args.get("q") or "").strip()
    code = (request.args.get("code") or "").strip()

    try:
        query = db_query_articles()

        if q:
            like_value = f"%{q}%"
            query = query.filter(
                (Article.name.ilike(like_value))
                | (Article.code.ilike(like_value))
                | (Article.barcode.ilike(like_value))
            )

        if code:
            query = query.filter(Article.code.ilike(f"%{code}%"))

        articles = query.order_by(Article.name.asc()).all()

        return render_template(
            "articles/article_search.html",
            title="Buscar artículo",
            subtitle="Consulte artículos por código, nombre o código de barras.",
            query=q,
            code=code,
            articles=articles,
        )

    except Exception:
        flash("Error al buscar artículos.", "danger")
        return render_template(
            "articles/article_search.html",
            title="Buscar artículo",
            subtitle="Consulte artículos por código, nombre o código de barras.",
            query=q,
            code=code,
            articles=[],
        )


# =========================================================
# RESUMEN DE STOCK POR ARTÍCULO
# =========================================================
@articles_bp.route("/article/<int:article_id>/summary", methods=["GET"])
@login_required
def article_summary(article_id: int):
    try:
        article = Article.query.get(article_id)
        if not article:
            raise ValueError("El artículo no existe.")

        summary = get_article_stock_summary(article_id)

        return render_template(
            "articles/article_summary.html",
            title="Resumen de artículo",
            subtitle="Visualice cantidades por bodega, minibodega o caja de herramientas.",
            article=article,
            summary=summary,
        )

    except (InventoryServiceError, ValueError) as exc:
        flash(str(exc), "danger")
        return render_template(
            "articles/article_summary.html",
            title="Resumen de artículo",
            subtitle="Visualice cantidades por bodega, minibodega o caja de herramientas.",
            article=None,
            summary=[],
        )

    except Exception:
        flash("Error al cargar el resumen del artículo.", "danger")
        return render_template(
            "articles/article_summary.html",
            title="Resumen de artículo",
            subtitle="Visualice cantidades por bodega, minibodega o caja de herramientas.",
            article=None,
            summary=[],
        )


# =========================================================
# REPORTE DE MOVIMIENTOS DE INVENTARIO
# =========================================================
@articles_bp.route("/stock/report", methods=["GET"])
@login_required
def stock_report():
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    article_code = (request.args.get("article_code") or "").strip()
    warehouse_id = (request.args.get("warehouse_id") or "").strip()
    movement_type = (request.args.get("movement_type") or "").strip()

    try:
        query = (
            InventoryLedger.query
            .join(Article, Article.id == InventoryLedger.article_id)
            .join(Warehouse, Warehouse.id == InventoryLedger.warehouse_id)
        )

        if date_from:
            query = query.filter(InventoryLedger.created_at >= date_from)

        if date_to:
            query = query.filter(InventoryLedger.created_at <= date_to)

        if article_code:
            query = query.filter(Article.code.ilike(f"%{article_code}%"))

        if warehouse_id:
            query = query.filter(InventoryLedger.warehouse_id == int(warehouse_id))

        if movement_type:
            query = query.filter(InventoryLedger.movement_type == movement_type)

        movements = query.order_by(InventoryLedger.created_at.desc()).limit(300).all()

        warehouses = Warehouse.query.order_by(Warehouse.name.asc()).all()

        return render_template(
            "articles/stock_report.html",
            title="Reporte de entradas y salidas",
            subtitle="Consulte movimientos por rango de fechas, artículo o bodega.",
            date_from=date_from,
            date_to=date_to,
            article_code=article_code,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
            movements=movements,
            warehouses=warehouses,
        )

    except Exception:
        flash("Error al cargar el reporte de inventario.", "danger")
        return render_template(
            "articles/stock_report.html",
            title="Reporte de entradas y salidas",
            subtitle="Consulte movimientos por rango de fechas, artículo o bodega.",
            date_from=date_from,
            date_to=date_to,
            article_code=article_code,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
            movements=[],
            warehouses=[],
        )


# =========================================================
# HELPER INTERNO DE CONSULTA BASE DE ARTÍCULOS
# =========================================================
def db_query_articles():
    return (
        Article.query
        .outerjoin(WarehouseStock, WarehouseStock.article_id == Article.id)
        .filter(Article.is_active.is_(True))
        .distinct()
    )