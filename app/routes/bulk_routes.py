from __future__ import annotations

import io

import pandas as pd
from flask import Blueprint, flash, redirect, request, send_file, url_for, render_template
from flask_login import login_required

from app.services.bulk_import_service import import_mechanics


bulk_bp = Blueprint("bulk", __name__, url_prefix="/bulk")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza encabezados de Excel para que el backend no dependa
    de mayúsculas, espacios o asteriscos de campos obligatorios.

    Ejemplos:
    - 'Código*' -> 'codigo'
    - ' nombre ' -> 'nombre'
    """
    df.columns = [
        str(col)
        .strip()
        .lower()
        .replace("*", "")
        for col in df.columns
    ]
    return df


@bulk_bp.route("/mechanics/template", methods=["GET"])
@login_required
def download_mechanics_template():
    """
    Descarga la plantilla Excel para carga masiva de mecánicos.
    Encabezados en español y con * para obligatorios.
    """
    df = pd.DataFrame(
        columns=[
            "codigo*",
            "nombre*",
            "activo",
        ]
    )

    output = io.BytesIO()
    df.to_excel(output, index=False, engine="openpyxl")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="plantilla_mecanicos.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bulk_bp.route("/mechanics/upload", methods=["POST"])
@login_required
def upload_mechanics():
    """
    Procesa la carga masiva de mecánicos desde un archivo .xlsx.

    Reglas:
    - si el código ya existe, actualiza
    - si no existe, crea
    - no duplica
    """
    file = request.files.get("file")

    if not file or not file.filename:
        flash("Debe seleccionar un archivo Excel.", "danger")
        return redirect(request.referrer or url_for("work_orders.create_work_order_page"))

    if not file.filename.lower().endswith(".xlsx"):
        flash("El archivo debe estar en formato .xlsx.", "danger")
        return redirect(request.referrer or url_for("work_orders.create_work_order_page"))

    try:
        df = pd.read_excel(file, dtype=str, engine="openpyxl")
        df = df.fillna("")
        df = normalize_columns(df)

        required_columns = {"codigo", "nombre"}
        received_columns = set(df.columns)

        missing_columns = required_columns - received_columns
        if missing_columns:
            flash(
                "Faltan columnas obligatorias en el archivo: "
                + ", ".join(sorted(missing_columns)),
                "danger",
            )
            return redirect(request.referrer or url_for("work_orders.create_work_order_page"))

        rows = df.to_dict(orient="records")
        result = import_mechanics(rows)

        flash(
            (
                "Carga masiva de mecánicos completada correctamente. "
                f"Creados: {result['created']}. "
                f"Actualizados: {result['updated']}. "
                f"Omitidos: {result['skipped']}."
            ),
            "success",
        )
        return redirect(request.referrer or url_for("work_orders.create_work_order_page"))

    except Exception as exc:
        flash(f"Error al procesar la carga masiva de mecánicos: {exc}", "danger")
        return redirect(request.referrer or url_for("work_orders.create_work_order_page"))
    
@bulk_bp.route("/", methods=["GET"])
@login_required
def bulk_home():
    return render_template(
        "bulk/index.html",
        title="Carga masiva",
        subtitle="Gestione cargas masivas de catálogos e inventario desde un solo lugar.",
    )