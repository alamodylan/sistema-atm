from app.models.request_routing_rule import RequestRoutingRule


# =========================================================
# CONSTANTES
# =========================================================

DEFAULT_ROUTING = {
    "has_rule": False,
    "routing_mode": None,
    "target_site_id": None,
    "requires_manager_review": True,
    "send_direct_to_warehouse": False,
    "send_direct_to_procurement": False,
}


# =========================================================
# RESOLVER ROUTING
# =========================================================

def resolve_request_routing(
    origin_site_id,
    request_type,
):
    """
    Resuelve cómo debe fluir una solicitud según:
    - predio origen
    - tipo de solicitud

    IMPORTANTE:
    Si no existe configuración,
    el sistema debe seguir funcionando EXACTAMENTE IGUAL.
    """

    rule = (
        RequestRoutingRule.query
        .filter(
            RequestRoutingRule.origin_site_id == origin_site_id,
            RequestRoutingRule.request_type == request_type,
            RequestRoutingRule.is_active.is_(True),
        )
        .first()
    )

    # =====================================================
    # SI NO EXISTE REGLA
    # =====================================================

    if not rule:
        return DEFAULT_ROUTING.copy()

    # =====================================================
    # DASHBOARD JEFATURA MISMO PREDIO
    # =====================================================

    if rule.routing_mode == "LOCAL_MANAGER_DASHBOARD":

        return {
            "has_rule": True,
            "routing_mode": rule.routing_mode,
            "target_site_id": origin_site_id,
            "requires_manager_review": True,
            "send_direct_to_warehouse": False,
            "send_direct_to_procurement": False,
            "rule": rule,
        }

    # =====================================================
    # DASHBOARD JEFATURA OTRO PREDIO
    # =====================================================

    if rule.routing_mode == "OTHER_SITE_MANAGER_DASHBOARD":

        return {
            "has_rule": True,
            "routing_mode": rule.routing_mode,
            "target_site_id": rule.target_site_id,
            "requires_manager_review": True,
            "send_direct_to_warehouse": False,
            "send_direct_to_procurement": False,
            "rule": rule,
        }

    # =====================================================
    # DIRECTO A BODEGA
    # =====================================================

    if rule.routing_mode == "DIRECT_TO_WAREHOUSE":

        return {
            "has_rule": True,
            "routing_mode": rule.routing_mode,
            "target_site_id": origin_site_id,
            "requires_manager_review": False,
            "send_direct_to_warehouse": True,
            "send_direct_to_procurement": False,
            "rule": rule,
        }

    # =====================================================
    # DIRECTO A PROVEEDURIA
    # =====================================================

    if rule.routing_mode == "DIRECT_TO_PROCUREMENT":

        return {
            "has_rule": True,
            "routing_mode": rule.routing_mode,
            "target_site_id": origin_site_id,
            "requires_manager_review": False,
            "send_direct_to_warehouse": False,
            "send_direct_to_procurement": True,
            "rule": rule,
        }

    # =====================================================
    # FALLBACK ABSOLUTO
    # =====================================================

    return DEFAULT_ROUTING.copy()


# =========================================================
# OBTENER REGLA
# =========================================================

def get_request_routing_rule(
    origin_site_id,
    request_type,
):
    return (
        RequestRoutingRule.query
        .filter(
            RequestRoutingRule.origin_site_id == origin_site_id,
            RequestRoutingRule.request_type == request_type,
        )
        .first()
    )


# =========================================================
# LISTAR REGLAS
# =========================================================

def get_all_request_routing_rules():
    return (
        RequestRoutingRule.query
        .order_by(
            RequestRoutingRule.origin_site_id.asc(),
            RequestRoutingRule.request_type.asc(),
        )
        .all()
    )