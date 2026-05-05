from app.extensions import db
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.site import Site
from app.models.user import User
from app.models.user_site_access import UserSiteAccess
from app.models.user_warehouse_access import UserWarehouseAccess
from app.models.warehouse import Warehouse


class UserAdminServiceError(Exception):
    pass


def _clean_text(value):
    if value is None:
        return None

    value = str(value).strip()
    return value if value else None


def _parse_int_list(values):
    result = []

    for value in values or []:
        value = _clean_text(value)

        if value is None:
            continue

        try:
            result.append(int(value))
        except ValueError as exc:
            raise UserAdminServiceError("Uno de los valores seleccionados no es válido.") from exc

    return list(set(result))


def list_users(include_inactive=True):
    query = User.query.order_by(User.full_name.asc(), User.username.asc())

    if not include_inactive:
        query = query.filter(User.is_active.is_(True))

    return query.all()


def get_user_or_404(user_id):
    return User.query.get_or_404(user_id)


def list_roles(include_inactive=True):
    query = Role.query.order_by(Role.name.asc())

    if not include_inactive:
        query = query.filter(Role.is_active.is_(True))

    return query.all()


def list_permissions():
    return Permission.query.order_by(Permission.name.asc()).all()


def list_sites(include_inactive=True):
    query = Site.query.order_by(Site.name.asc())

    if not include_inactive:
        query = query.filter(Site.is_active.is_(True))

    return query.all()


def list_warehouses_grouped_by_site(include_inactive=True):
    query = Warehouse.query.order_by(
        Warehouse.site_id.asc(),
        Warehouse.warehouse_type.asc(),
        Warehouse.name.asc(),
    )

    if not include_inactive:
        query = query.filter(Warehouse.is_active.is_(True))

    warehouses = query.all()
    grouped = {}

    for warehouse in warehouses:
        grouped.setdefault(warehouse.site_id, []).append(warehouse)

    return grouped


def create_user(
    *,
    username,
    full_name,
    email=None,
    password=None,
    role_id=None,
    site_ids=None,
    warehouse_ids=None,
    is_shared_account=False,
    barcode_value=None,
    created_by_user_id=None,
):
    username = _clean_text(username)
    full_name = _clean_text(full_name)
    email = _clean_text(email)
    password = _clean_text(password)
    barcode_value = _clean_text(barcode_value)

    if not username:
        raise UserAdminServiceError("El usuario es obligatorio.")

    if not full_name:
        raise UserAdminServiceError("El nombre completo es obligatorio.")

    if not password:
        raise UserAdminServiceError("La contraseña es obligatoria.")

    try:
        role_id = int(role_id)
    except (TypeError, ValueError) as exc:
        raise UserAdminServiceError("Debe seleccionar un rol válido.") from exc

    role = Role.query.filter_by(id=role_id, is_active=True).first()

    if not role:
        raise UserAdminServiceError("El rol seleccionado no existe o está inactivo.")

    existing_username = User.query.filter(
        db.func.lower(User.username) == username.lower()
    ).first()

    if existing_username:
        raise UserAdminServiceError("Ya existe un usuario con ese nombre de usuario.")

    if email:
        existing_email = User.query.filter(
            db.func.lower(User.email) == email.lower()
        ).first()

        if existing_email:
            raise UserAdminServiceError("Ya existe un usuario con ese correo.")

    if barcode_value:
        existing_barcode = User.query.filter(
            db.func.lower(User.barcode_value) == barcode_value.lower()
        ).first()

        if existing_barcode:
            raise UserAdminServiceError("Ya existe un usuario con ese código/barcode.")

    user = User(
        username=username,
        full_name=full_name,
        email=email,
        role_id=role.id,
        is_active=True,
        is_shared_account=bool(is_shared_account),
        barcode_value=barcode_value,
        created_by_user_id=created_by_user_id,
    )

    user.set_password(password)

    db.session.add(user)
    db.session.flush()

    _sync_user_access(
        user=user,
        site_ids=site_ids,
        warehouse_ids=warehouse_ids,
    )

    db.session.commit()

    return user


def update_user(
    *,
    user_id,
    username,
    full_name,
    email=None,
    password=None,
    role_id=None,
    site_ids=None,
    warehouse_ids=None,
    is_active=True,
    is_shared_account=False,
    barcode_value=None,
):
    user = get_user_or_404(user_id)

    username = _clean_text(username)
    full_name = _clean_text(full_name)
    email = _clean_text(email)
    password = _clean_text(password)
    barcode_value = _clean_text(barcode_value)

    if not username:
        raise UserAdminServiceError("El usuario es obligatorio.")

    if not full_name:
        raise UserAdminServiceError("El nombre completo es obligatorio.")

    try:
        role_id = int(role_id)
    except (TypeError, ValueError) as exc:
        raise UserAdminServiceError("Debe seleccionar un rol válido.") from exc

    role = Role.query.filter_by(id=role_id, is_active=True).first()

    if not role:
        raise UserAdminServiceError("El rol seleccionado no existe o está inactivo.")

    existing_username = User.query.filter(
        db.func.lower(User.username) == username.lower(),
        User.id != user.id,
    ).first()

    if existing_username:
        raise UserAdminServiceError("Ya existe otro usuario con ese nombre de usuario.")

    if email:
        existing_email = User.query.filter(
            db.func.lower(User.email) == email.lower(),
            User.id != user.id,
        ).first()

        if existing_email:
            raise UserAdminServiceError("Ya existe otro usuario con ese correo.")

    if barcode_value:
        existing_barcode = User.query.filter(
            db.func.lower(User.barcode_value) == barcode_value.lower(),
            User.id != user.id,
        ).first()

        if existing_barcode:
            raise UserAdminServiceError("Ya existe otro usuario con ese código/barcode.")

    user.username = username
    user.full_name = full_name
    user.email = email
    user.role_id = role.id
    user.is_active = bool(is_active)
    user.is_shared_account = bool(is_shared_account)
    user.barcode_value = barcode_value

    if password:
        user.set_password(password)

    _sync_user_access(
        user=user,
        site_ids=site_ids,
        warehouse_ids=warehouse_ids,
    )

    db.session.commit()

    return user


def toggle_user_status(user_id):
    user = get_user_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    return user


def get_user_site_ids(user):
    return [access.site_id for access in user.site_accesses]


def get_user_warehouse_ids(user):
    return [access.warehouse_id for access in user.warehouse_accesses]


def _sync_user_access(*, user, site_ids=None, warehouse_ids=None):
    site_ids = _parse_int_list(site_ids)
    warehouse_ids = _parse_int_list(warehouse_ids)

    warehouses = []

    if warehouse_ids:
        warehouses = Warehouse.query.filter(
            Warehouse.id.in_(warehouse_ids),
            Warehouse.is_active.is_(True),
        ).all()

        valid_warehouse_ids = {warehouse.id for warehouse in warehouses}

        invalid_warehouse_ids = set(warehouse_ids) - valid_warehouse_ids

        if invalid_warehouse_ids:
            raise UserAdminServiceError("Una o más bodegas seleccionadas no existen o están inactivas.")

        for warehouse in warehouses:
            site_ids.append(warehouse.site_id)

    site_ids = list(set(site_ids))

    if site_ids:
        valid_sites = Site.query.filter(
            Site.id.in_(site_ids),
            Site.is_active.is_(True),
        ).all()

        valid_site_ids = {site.id for site in valid_sites}

        invalid_site_ids = set(site_ids) - valid_site_ids

        if invalid_site_ids:
            raise UserAdminServiceError("Uno o más predios seleccionados no existen o están inactivos.")

    UserSiteAccess.query.filter_by(user_id=user.id).delete()
    UserWarehouseAccess.query.filter_by(user_id=user.id).delete()

    for site_id in site_ids:
        db.session.add(
            UserSiteAccess(
                user_id=user.id,
                site_id=site_id,
            )
        )

    for warehouse_id in warehouse_ids:
        db.session.add(
            UserWarehouseAccess(
                user_id=user.id,
                warehouse_id=warehouse_id,
            )
        )


def list_roles_with_permissions():
    return Role.query.order_by(Role.name.asc()).all()


def get_role_or_404(role_id):
    return Role.query.get_or_404(role_id)


def create_role(*, code, name, description=None, permission_ids=None):
    code = _clean_text(code)
    name = _clean_text(name)
    description = _clean_text(description)

    if not code:
        raise UserAdminServiceError("El código del rol es obligatorio.")

    if not name:
        raise UserAdminServiceError("El nombre del rol es obligatorio.")

    code = code.upper()

    existing = Role.query.filter(
        db.func.upper(Role.code) == code
    ).first()

    if existing:
        raise UserAdminServiceError("Ya existe un rol con ese código.")

    role = Role(
        code=code,
        name=name,
        description=description,
        is_active=True,
    )

    db.session.add(role)
    db.session.flush()

    _sync_role_permissions(
        role=role,
        permission_ids=permission_ids,
    )

    db.session.commit()

    return role


def update_role(*, role_id, code, name, description=None, is_active=True, permission_ids=None):
    role = get_role_or_404(role_id)

    code = _clean_text(code)
    name = _clean_text(name)
    description = _clean_text(description)

    if not code:
        raise UserAdminServiceError("El código del rol es obligatorio.")

    if not name:
        raise UserAdminServiceError("El nombre del rol es obligatorio.")

    code = code.upper()

    existing = Role.query.filter(
        db.func.upper(Role.code) == code,
        Role.id != role.id,
    ).first()

    if existing:
        raise UserAdminServiceError("Ya existe otro rol con ese código.")

    role.code = code
    role.name = name
    role.description = description
    role.is_active = bool(is_active)

    _sync_role_permissions(
        role=role,
        permission_ids=permission_ids,
    )

    db.session.commit()

    return role


def _sync_role_permissions(*, role, permission_ids=None):
    permission_ids = _parse_int_list(permission_ids)

    if permission_ids:
        valid_permissions = Permission.query.filter(
            Permission.id.in_(permission_ids)
        ).all()

        valid_permission_ids = {permission.id for permission in valid_permissions}

        invalid_permission_ids = set(permission_ids) - valid_permission_ids

        if invalid_permission_ids:
            raise UserAdminServiceError("Uno o más permisos seleccionados no existen.")

    RolePermission.query.filter_by(role_id=role.id).delete()

    for permission_id in permission_ids:
        db.session.add(
            RolePermission(
                role_id=role.id,
                permission_id=permission_id,
            )
        )


def get_role_permission_ids(role):
    return [
        role_permission.permission_id
        for role_permission in role.role_permissions
    ]