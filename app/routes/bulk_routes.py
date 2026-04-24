from __future__ import annotations

import io

import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required

from app.services.bulk_import_service import (
    BulkImportError,
    import_articles,
    import_categories,
    import_equipment,
    import_location_stock,
    import_locations,
    import_mechanics,
    import_suppliers,
    import_units,
    import_warehouses,
    import_warehouse_stock,
)

bulk_bp = Blueprint("bulk", __name__, url_prefix="/bulk")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(col).strip().lower().replace("*", "") for col in df.columns]
    return df


def _read_excel(file):
    df = pd.read_excel(file, dtype=str, engine="openpyxl")
    df = df.fillna("")
    return normalize_columns(df)


def _validate_required_columns(df: pd.DataFrame, required_columns: set[str]) -> None:
    missing = required_columns - set(df.columns)
    if missing:
        raise BulkImportError(
            "Faltan columnas obligatorias: " + ", ".join(sorted(missing))
        )


def _send_template(columns: list[str], filename: str):
    df = pd.DataFrame(columns=columns)
    output = io.BytesIO()
    df.to_excel(output, index=False, engine="openpyxl")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bulk_bp.route("/", methods=["GET"])
@login_required
def bulk_home():
    return render_template(
        "bulk/index.html",
        title="Carga masiva",
        subtitle="Gestione cargas masivas de catálogos e inventario desde un solo lugar.",
    )


# =========================================================
# MECÁNICOS
# =========================================================
@bulk_bp.route("/mechanics/template", methods=["GET"])
@login_required
def download_mechanics_template():
    return _send_template(
        ["codigo*", "nombre*", "activo"],
        "plantilla_mecanicos.xlsx",
    )


@bulk_bp.route("/mechanics/upload", methods=["POST"])
@login_required
def upload_mechanics():
    active_site_id = session.get("active_site_id")
    if not active_site_id:
        flash("Debe seleccionar un predio activo antes de realizar una carga masiva.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo", "nombre"})
        result = import_mechanics(df.to_dict(orient="records"), site_id=int(active_site_id))
        flash(
            f"Mecánicos cargados. Creados: {result['created']}. "
            f"Actualizados: {result['updated']}. Omitidos: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de mecánicos: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# UNIDADES
# =========================================================
@bulk_bp.route("/units/template", methods=["GET"])
@login_required
def download_units_template():
    return _send_template(
        ["codigo*", "nombre*"],
        "plantilla_unidades.xlsx",
    )


@bulk_bp.route("/units/upload", methods=["POST"])
@login_required
def upload_units():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo", "nombre"})
        result = import_units(df.to_dict(orient="records"))
        flash(
            f"Unidades cargadas. Creadas: {result['created']}. "
            f"Actualizadas: {result['updated']}. Omitidas: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de unidades: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# CATEGORÍAS
# =========================================================
@bulk_bp.route("/categories/template", methods=["GET"])
@login_required
def download_categories_template():
    return _send_template(
        ["codigo*", "nombre*", "descripcion"],
        "plantilla_categorias.xlsx",
    )


@bulk_bp.route("/categories/upload", methods=["POST"])
@login_required
def upload_categories():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo", "nombre"})
        result = import_categories(df.to_dict(orient="records"))
        flash(
            f"Categorías cargadas. Creadas: {result['created']}. "
            f"Actualizadas: {result['updated']}. Omitidas: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de categorías: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# BODEGAS
# =========================================================
@bulk_bp.route("/warehouses/template", methods=["GET"])
@login_required
def download_warehouses_template():
    return _send_template(
        ["codigo*", "nombre*", "tipo_bodega*", "activo"],
        "plantilla_bodegas.xlsx",
    )


@bulk_bp.route("/warehouses/upload", methods=["POST"])
@login_required
def upload_warehouses():
    active_site_id = session.get("active_site_id")
    if not active_site_id:
        flash("Debe seleccionar un predio activo antes de realizar una carga masiva.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo", "nombre", "tipo_bodega"})
        result = import_warehouses(df.to_dict(orient="records"), site_id=int(active_site_id))
        flash(
            f"Bodegas cargadas. Creadas: {result['created']}. "
            f"Actualizadas: {result['updated']}. Omitidas: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de bodegas: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# UBICACIONES
# =========================================================
@bulk_bp.route("/locations/template", methods=["GET"])
@login_required
def download_locations_template():
    return _send_template(
        ["codigo_bodega*", "codigo*", "pasillo", "estante", "nivel", "posicion", "descripcion", "activo"],
        "plantilla_ubicaciones.xlsx",
    )


@bulk_bp.route("/locations/upload", methods=["POST"])
@login_required
def upload_locations():
    active_site_id = session.get("active_site_id")
    if not active_site_id:
        flash("Debe seleccionar un predio activo antes de realizar una carga masiva.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo_bodega", "codigo"})
        result = import_locations(df.to_dict(orient="records"), site_id=int(active_site_id))
        flash(
            f"Ubicaciones cargadas. Creadas: {result['created']}. "
            f"Actualizadas: {result['updated']}. Omitidas: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de ubicaciones: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# ARTÍCULOS
# =========================================================
@bulk_bp.route("/articles/template", methods=["GET"])
@login_required
def download_articles_template():
    return _send_template(
        [
            "codigo*",
            "nombre*",
            "codigo_unidad*",
            "codigo_categoria",
            "nombre_categoria",
            "nombre_subcategoria",
            "descripcion",
            "codigo_barras",
            "codigo_sap",
            "es_herramienta",
            "activo",
        ],
        "plantilla_articulos.xlsx",
    )


@bulk_bp.route("/articles/upload", methods=["POST"])
@login_required
def upload_articles():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo", "nombre", "codigo_unidad"})
        result = import_articles(df.to_dict(orient="records"))
        flash(
            f"Artículos cargados. Creados: {result['created']}. "
            f"Actualizados: {result['updated']}. Omitidos: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de artículos: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# PROVEEDORES
# =========================================================
@bulk_bp.route("/suppliers/template", methods=["GET"])
@login_required
def download_suppliers_template():
    return _send_template(
        [
            "codigo",
            "nombre_comercial*",
            "nombre_legal",
            "cedula_juridica",
            "contacto",
            "correo",
            "telefono",
            "direccion",
            "condiciones_pago",
            "moneda",
            "activo",
        ],
        "plantilla_proveedores.xlsx",
    )


@bulk_bp.route("/suppliers/upload", methods=["POST"])
@login_required
def upload_suppliers():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"nombre_comercial"})
        result = import_suppliers(df.to_dict(orient="records"))
        flash(
            f"Proveedores cargados. Creados: {result['created']}. "
            f"Actualizados: {result['updated']}. Omitidos: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de proveedores: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# EQUIPOS
# =========================================================
@bulk_bp.route("/equipment/template", methods=["GET"])
@login_required
def download_equipment_template():
    return _send_template(
        ["codigo*", "tipo*", "descripcion", "cantidad_ejes", "tamano", "activo"],
        "plantilla_equipos.xlsx",
    )


@bulk_bp.route("/equipment/upload", methods=["POST"])
@login_required
def upload_equipment():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo", "tipo"})
        result = import_equipment(df.to_dict(orient="records"))
        flash(
            f"Equipos cargados. Creados: {result['created']}. "
            f"Actualizados: {result['updated']}. Omitidos: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de equipos: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# STOCK POR BODEGA
# =========================================================
@bulk_bp.route("/warehouse-stock/template", methods=["GET"])
@login_required
def download_warehouse_stock_template():
    return _send_template(
        ["codigo_bodega*", "codigo_articulo*", "cantidad*"],
        "plantilla_stock_bodega.xlsx",
    )


@bulk_bp.route("/warehouse-stock/upload", methods=["POST"])
@login_required
def upload_warehouse_stock():
    active_site_id = session.get("active_site_id")
    if not active_site_id:
        flash("Debe seleccionar un predio activo antes de realizar una carga masiva.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo_bodega", "codigo_articulo", "cantidad"})
        result = import_warehouse_stock(
            df.to_dict(orient="records"),
            site_id=int(active_site_id),
            performed_by_user_id=current_user.id,
        )
        flash(
            f"Stock por bodega cargado. Creados: {result['created']}. "
            f"Actualizados: {result['updated']}. Omitidos: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de stock por bodega: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))


# =========================================================
# STOCK POR UBICACIÓN
# =========================================================
@bulk_bp.route("/location-stock/template", methods=["GET"])
@login_required
def download_location_stock_template():
    return _send_template(
        ["codigo_bodega*", "codigo_ubicacion*", "codigo_articulo*", "cantidad*"],
        "plantilla_stock_ubicacion.xlsx",
    )


@bulk_bp.route("/location-stock/upload", methods=["POST"])
@login_required
def upload_location_stock():
    active_site_id = session.get("active_site_id")
    if not active_site_id:
        flash("Debe seleccionar un predio activo antes de realizar una carga masiva.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(url_for("bulk.bulk_home"))

    try:
        df = _read_excel(file)
        _validate_required_columns(df, {"codigo_bodega", "codigo_ubicacion", "codigo_articulo", "cantidad"})
        result = import_location_stock(
            df.to_dict(orient="records"),
            site_id=int(active_site_id),
            performed_by_user_id=current_user.id,
        )
        flash(
            f"Stock por ubicación cargado. Creados: {result['created']}. "
            f"Actualizados: {result['updated']}. Omitidos: {result['skipped']}.",
            "success",
        )
    except Exception as exc:
        flash(f"Error al procesar la carga de stock por ubicación: {exc}", "danger")

    return redirect(url_for("bulk.bulk_home"))