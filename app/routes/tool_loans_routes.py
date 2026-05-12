from flask import Blueprint, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from app.services.tool_loan_service import (
    ToolLoanServiceError,
    deliver_tool_loan,
    list_active_tool_loans,
    list_requested_tool_loans,
    receive_tool_return,
)

tool_loans_bp = Blueprint(
    "tool_loans",
    __name__,
    url_prefix="/tool-loans",
)


@tool_loans_bp.route("/")
@login_required
def index():
    active_site_id = session.get("active_site_id")

    requested_loans = list_requested_tool_loans(
        site_id=active_site_id,
    )

    active_loans = list_active_tool_loans(
        site_id=active_site_id,
    )

    return render_template(
        "tool_loans/index.html",
        requested_loans=requested_loans,
        active_loans=active_loans,
    )


@tool_loans_bp.route("/<int:tool_loan_id>/deliver", methods=["POST"])
@login_required
def deliver(tool_loan_id: int):
    try:
        deliver_tool_loan(
            tool_loan_id=tool_loan_id,
            delivered_by_user_id=current_user.id,
        )

        flash("Herramienta prestada correctamente.", "success")

    except ToolLoanServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("tool_loans.index"))


@tool_loans_bp.route("/<int:tool_loan_id>/receive-return", methods=["POST"])
@login_required
def receive_return(tool_loan_id: int):
    try:
        receive_tool_return(
            tool_loan_id=tool_loan_id,
            received_by_user_id=current_user.id,
        )

        flash("Devolución recibida correctamente.", "success")

    except ToolLoanServiceError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("tool_loans.index"))