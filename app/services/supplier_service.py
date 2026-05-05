from app.extensions import db
from app.models.article import Article
from app.models.article_supplier import ArticleSupplier
from app.models.supplier import Supplier


class SupplierServiceError(Exception):
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


def list_suppliers(include_inactive=True, search=None):
    query = Supplier.query

    search = _clean_text(search)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                Supplier.code.ilike(pattern),
                Supplier.commercial_name.ilike(pattern),
                Supplier.legal_name.ilike(pattern),
                Supplier.tax_id.ilike(pattern),
                Supplier.contact_name.ilike(pattern),
                Supplier.email.ilike(pattern),
                Supplier.phone.ilike(pattern),
            )
        )

    if not include_inactive:
        query = query.filter(Supplier.is_active.is_(True))

    return query.order_by(Supplier.commercial_name.asc()).all()


def get_supplier(supplier_id):
    return Supplier.query.get(supplier_id)


def get_supplier_or_404(supplier_id):
    return Supplier.query.get_or_404(supplier_id)


def create_supplier(
    code=None,
    commercial_name=None,
    legal_name=None,
    tax_id=None,
    contact_name=None,
    email=None,
    phone=None,
    address=None,
    payment_terms=None,
    currency_code=None,
):
    code = _normalize_code(code)
    commercial_name = _clean_text(commercial_name)
    legal_name = _clean_text(legal_name)
    tax_id = _clean_text(tax_id)
    contact_name = _clean_text(contact_name)
    email = _clean_text(email)
    phone = _clean_text(phone)
    address = _clean_text(address)
    payment_terms = _clean_text(payment_terms)
    currency_code = _normalize_code(currency_code)

    if not commercial_name:
        raise SupplierServiceError("El nombre comercial del proveedor es obligatorio.")

    if code:
        existing = Supplier.query.filter(
            db.func.upper(Supplier.code) == code
        ).first()

        if existing:
            raise SupplierServiceError("Ya existe un proveedor con ese código.")

    supplier = Supplier(
        code=code,
        commercial_name=commercial_name,
        legal_name=legal_name,
        tax_id=tax_id,
        contact_name=contact_name,
        email=email,
        phone=phone,
        address=address,
        payment_terms=payment_terms,
        currency_code=currency_code,
        is_active=True,
    )

    db.session.add(supplier)
    db.session.commit()

    return supplier


def update_supplier(
    supplier_id,
    code=None,
    commercial_name=None,
    legal_name=None,
    tax_id=None,
    contact_name=None,
    email=None,
    phone=None,
    address=None,
    payment_terms=None,
    currency_code=None,
    is_active=True,
):
    supplier = get_supplier_or_404(supplier_id)

    code = _normalize_code(code)
    commercial_name = _clean_text(commercial_name)
    legal_name = _clean_text(legal_name)
    tax_id = _clean_text(tax_id)
    contact_name = _clean_text(contact_name)
    email = _clean_text(email)
    phone = _clean_text(phone)
    address = _clean_text(address)
    payment_terms = _clean_text(payment_terms)
    currency_code = _normalize_code(currency_code)

    if not commercial_name:
        raise SupplierServiceError("El nombre comercial del proveedor es obligatorio.")

    if code:
        existing = Supplier.query.filter(
            db.func.upper(Supplier.code) == code,
            Supplier.id != supplier.id,
        ).first()

        if existing:
            raise SupplierServiceError("Ya existe otro proveedor con ese código.")

    supplier.code = code
    supplier.commercial_name = commercial_name
    supplier.legal_name = legal_name
    supplier.tax_id = tax_id
    supplier.contact_name = contact_name
    supplier.email = email
    supplier.phone = phone
    supplier.address = address
    supplier.payment_terms = payment_terms
    supplier.currency_code = currency_code
    supplier.is_active = bool(is_active)

    db.session.commit()

    return supplier


def toggle_supplier_status(supplier_id):
    supplier = get_supplier_or_404(supplier_id)
    supplier.is_active = not supplier.is_active
    db.session.commit()
    return supplier


def search_active_articles(search=None, limit=25):
    query = Article.query.filter(Article.is_active.is_(True))

    search = _clean_text(search)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                Article.code.ilike(pattern),
                Article.name.ilike(pattern),
                Article.description.ilike(pattern),
                Article.barcode.ilike(pattern),
                Article.sap_code.ilike(pattern),
            )
        )

    return query.order_by(Article.code.asc()).limit(limit).all()


def get_supplier_article_links(supplier_id, include_inactive=True):
    query = (
        ArticleSupplier.query
        .filter(ArticleSupplier.supplier_id == supplier_id)
        .join(Article, Article.id == ArticleSupplier.article_id)
        .order_by(Article.code.asc())
    )

    if not include_inactive:
        query = query.filter(ArticleSupplier.is_active.is_(True))

    return query.all()


def add_article_to_supplier(supplier_id, article_id):
    supplier = get_supplier_or_404(supplier_id)

    article = Article.query.filter_by(
        id=article_id,
        is_active=True,
    ).first()

    if not article:
        raise SupplierServiceError("El artículo seleccionado no existe o está inactivo.")

    existing = ArticleSupplier.query.filter_by(
        supplier_id=supplier.id,
        article_id=article.id,
    ).first()

    if existing:
        if existing.is_active:
            raise SupplierServiceError("Ese artículo ya está ligado a este proveedor.")

        existing.is_active = True
        db.session.commit()
        return existing

    link = ArticleSupplier(
        supplier_id=supplier.id,
        article_id=article.id,
        is_active=True,
    )

    db.session.add(link)
    db.session.commit()

    return link


def remove_article_from_supplier(supplier_id, article_supplier_id):
    supplier = get_supplier_or_404(supplier_id)

    link = ArticleSupplier.query.filter_by(
        id=article_supplier_id,
        supplier_id=supplier.id,
    ).first()

    if not link:
        raise SupplierServiceError("La relación artículo-proveedor no existe.")

    link.is_active = False
    db.session.commit()

    return link


def reactivate_article_supplier(supplier_id, article_supplier_id):
    supplier = get_supplier_or_404(supplier_id)

    link = ArticleSupplier.query.filter_by(
        id=article_supplier_id,
        supplier_id=supplier.id,
    ).first()

    if not link:
        raise SupplierServiceError("La relación artículo-proveedor no existe.")

    link.is_active = True
    db.session.commit()

    return link