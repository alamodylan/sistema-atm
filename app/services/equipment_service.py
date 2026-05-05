from app.extensions import db
from app.models.equipment import Equipment
from app.models.equipment_type import EquipmentType


class EquipmentServiceError(Exception):
    pass


def _clean_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def _normalize_code(value):
    value = _clean_text(value)
    if not value:
        return None
    return value.upper()


def list_equipment(include_inactive=True):
    query = Equipment.query.order_by(Equipment.code.asc())

    if not include_inactive:
        query = query.filter(Equipment.is_active.is_(True))

    return query.all()


def get_equipment(equipment_id):
    return Equipment.query.get(equipment_id)


def get_equipment_or_404(equipment_id):
    return Equipment.query.get_or_404(equipment_id)


def list_equipment_types(include_inactive=True):
    query = EquipmentType.query.order_by(EquipmentType.name.asc())

    if not include_inactive:
        query = query.filter(EquipmentType.is_active.is_(True))

    return query.all()


def get_equipment_type(equipment_type_id):
    return EquipmentType.query.get(equipment_type_id)


def get_equipment_type_or_404(equipment_type_id):
    return EquipmentType.query.get_or_404(equipment_type_id)


def create_equipment_type(code, name, description=None):
    code = _normalize_code(code)
    name = _clean_text(name)
    description = _clean_text(description)

    if not code:
        raise EquipmentServiceError("El código del tipo de equipo es obligatorio.")

    if not name:
        raise EquipmentServiceError("El nombre del tipo de equipo es obligatorio.")

    existing = EquipmentType.query.filter(
        db.func.upper(EquipmentType.code) == code
    ).first()

    if existing:
        raise EquipmentServiceError("Ya existe un tipo de equipo con ese código.")

    equipment_type = EquipmentType(
        code=code,
        name=name.upper(),
        description=description,
        is_active=True,
    )

    db.session.add(equipment_type)
    db.session.commit()

    return equipment_type


def update_equipment_type(equipment_type_id, code, name, description=None, is_active=True):
    equipment_type = get_equipment_type_or_404(equipment_type_id)

    code = _normalize_code(code)
    name = _clean_text(name)
    description = _clean_text(description)

    if not code:
        raise EquipmentServiceError("El código del tipo de equipo es obligatorio.")

    if not name:
        raise EquipmentServiceError("El nombre del tipo de equipo es obligatorio.")

    existing = EquipmentType.query.filter(
        db.func.upper(EquipmentType.code) == code,
        EquipmentType.id != equipment_type.id,
    ).first()

    if existing:
        raise EquipmentServiceError("Ya existe otro tipo de equipo con ese código.")

    equipment_type.code = code
    equipment_type.name = name.upper()
    equipment_type.description = description
    equipment_type.is_active = bool(is_active)

    db.session.commit()

    return equipment_type


def toggle_equipment_type_status(equipment_type_id):
    equipment_type = get_equipment_type_or_404(equipment_type_id)
    equipment_type.is_active = not equipment_type.is_active
    db.session.commit()
    return equipment_type


def create_equipment(
    code,
    equipment_type_id,
    description=None,
    axle_count=None,
    size_label=None,
):
    code = _normalize_code(code)
    description = _clean_text(description)
    size_label = _clean_text(size_label)

    if not code:
        raise EquipmentServiceError("El código del equipo es obligatorio.")

    equipment_type = EquipmentType.query.filter_by(
        id=equipment_type_id,
        is_active=True,
    ).first()

    if not equipment_type:
        raise EquipmentServiceError("Debe seleccionar un tipo de equipo activo.")

    existing = Equipment.query.filter(
        db.func.upper(Equipment.code) == code
    ).first()

    if existing:
        raise EquipmentServiceError("Ya existe un equipo con ese código.")

    axle_count = _parse_optional_int(axle_count, "La cantidad de ejes debe ser un número entero.")

    equipment = Equipment(
        code=code,
        equipment_type_id=equipment_type.id,
        equipment_type=equipment_type.code,
        description=description,
        axle_count=axle_count,
        size_label=size_label,
        is_active=True,
    )

    db.session.add(equipment)
    db.session.commit()

    return equipment


def update_equipment(
    equipment_id,
    code,
    equipment_type_id,
    description=None,
    axle_count=None,
    size_label=None,
    is_active=True,
):
    equipment = get_equipment_or_404(equipment_id)

    code = _normalize_code(code)
    description = _clean_text(description)
    size_label = _clean_text(size_label)

    if not code:
        raise EquipmentServiceError("El código del equipo es obligatorio.")

    equipment_type = EquipmentType.query.filter_by(
        id=equipment_type_id,
        is_active=True,
    ).first()

    if not equipment_type:
        raise EquipmentServiceError("Debe seleccionar un tipo de equipo activo.")

    existing = Equipment.query.filter(
        db.func.upper(Equipment.code) == code,
        Equipment.id != equipment.id,
    ).first()

    if existing:
        raise EquipmentServiceError("Ya existe otro equipo con ese código.")

    axle_count = _parse_optional_int(axle_count, "La cantidad de ejes debe ser un número entero.")

    equipment.code = code
    equipment.equipment_type_id = equipment_type.id
    equipment.equipment_type = equipment_type.code
    equipment.description = description
    equipment.axle_count = axle_count
    equipment.size_label = size_label
    equipment.is_active = bool(is_active)

    db.session.commit()

    return equipment


def toggle_equipment_status(equipment_id):
    equipment = get_equipment_or_404(equipment_id)
    equipment.is_active = not equipment.is_active
    db.session.commit()
    return equipment


def _parse_optional_int(value, error_message):
    value = _clean_text(value)

    if value is None:
        return None

    try:
        number = int(value)
    except ValueError as exc:
        raise EquipmentServiceError(error_message) from exc

    if number < 0:
        raise EquipmentServiceError("La cantidad de ejes no puede ser negativa.")

    return number