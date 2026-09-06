import uuid
from sqlalchemy.orm import Session, selectinload, joinedload
from app.db.models.products import Product
from app.db.models.category import Category
from app.db.models.album_detail import AlbumDetail
from app.db.models.merch_detail import MerchDetail
from app.db.models.genre import AlbumGenre
from app.db.models.idol import Idol
from app.db.models.group import Group
from app.db.models.user import Users
from app.schema.products import ProductRead, ProductCreate
from typing import List

# Company-scoping for update/delete/image-replace only (see docs/project_status.md
# SS4 item 10). A product has no company_id column of its own; its owner, if any,
# is resolved by whichever of album_details/merch_details references it -
# the same dual-FK "which row exists, then which of idol_id/group_id is set"
# lookup as album_detail_service._resolve_company_id / merch_detail_service's
# twin - rather than a direct column check, per docs/database-design.md SS6's
# note on this. A product tied to neither (plain merch not linked to any
# idol/group) has no company owner and stays manager-agnostic, matching the
# permissive behavior this project already had for every product before this -
# only a product actually tied to talent is scoped. add_product/add_bulk_products
# are deliberately NOT scoped: a bare Product row is created before any
# album_details/merch_details row exists to attach it to a company, so
# there is nothing to check yet at creation time - that's handled when the
# details row is created, by album_detail_service/merch_detail_service's
# own scoping.

def _resolve_product_company_id(db: Session, product_id: uuid.UUID):
    album = db.get(AlbumDetail, product_id)
    if album:
        if album.idol_id is not None:
            idol = db.get(Idol, album.idol_id)
            return idol.company_id if idol else None
        if album.group_id is not None:
            group = db.get(Group, album.group_id)
            return group.company_id if group else None
        return None
    merch = db.get(MerchDetail, product_id)
    if merch:
        if merch.idol_id is not None:
            idol = db.get(Idol, merch.idol_id)
            return idol.company_id if idol else None
        if merch.group_id is not None:
            group = db.get(Group, merch.group_id)
            return group.company_id if group else None
        return None
    return None  # plain merch - no company owner

def _manager_scope_violation(db: Session, current_user: Users, product_id: uuid.UUID) -> bool:
    if current_user.role != "manager":
        return False
    company_id = _resolve_product_company_id(db, product_id)
    if company_id is None:
        return False  # ownerless product - any manager may manage it
    return current_user.company_id != company_id

def List_of_products(db:Session):
    db_products = db.query(Product).options(selectinload(Product.category)).all()
    if not db_products:
        return False
    return db_products

def search_product(db:Session, id:uuid.UUID):
    db_product = db.query(Product).options(selectinload(Product.category)).filter(Product.id==id).first()
    if not db_product:
        return False
    return {
        "id": db_product.id,
        "name": db_product.name,
        "price": db_product.price,
        "description": db_product.description,
        "quantity": db_product.quantity,
        "image_url": db_product.image_url,
        "category": db_product.category
    }

def add_product(db: Session, product:ProductCreate):
    if not db.get(Category, product.category_id):
        return False  # invalid category_id — was an uncaught IntegrityError -> 500 at commit
    db_product = Product(**product.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def update_product(db:Session, id:uuid.UUID, product:ProductCreate, current_user:Users):
    db_product = db.get(Product, id)
    if not db_product:
        return False
    if _manager_scope_violation(db, current_user, id):
        return "forbidden"
    if not db.get(Category, product.category_id):
        return "category_not_found"  # was an uncaught IntegrityError -> 500 at commit
    db_product.name = product.name
    db_product.description = product.description
    db_product.price = product.price
    db_product.quantity = product.quantity
    db_product.category_id = product.category_id
    if product.image_url is not None:
        db_product.image_url = product.image_url
    db.commit()
    db.refresh(db_product)
    return db_product

def set_product_image(db: Session, id: uuid.UUID, image_url: str, current_user: Users):
    """Used by the dedicated /products/{id}/image upload endpoint — updates
    only the image, leaving every other field untouched (unlike
    update_product, which replaces the whole row from a ProductCreate)."""
    db_product = db.get(Product, id)
    if not db_product:
        return False
    if _manager_scope_violation(db, current_user, id):
        return "forbidden"
    db_product.image_url = image_url
    db.commit()
    db.refresh(db_product)
    return db_product

def delete_product(db:Session, id: uuid.UUID, current_user: Users):
    db_product = db.get(Product, id)
    if not db_product:
        return False
    if _manager_scope_violation(db, current_user, id):
        return "forbidden"
    db.delete(db_product)
    db.commit()
    return db_product

def add_bulk_products(db:Session, product:List[ProductRead]):
    db_products = [Product(**p.model_dump()) for p in product]
    if not db_products:
        return False
    # All-or-nothing: check every referenced category exists before saving
    # any of them — was an uncaught IntegrityError -> 500 at commit.
    category_ids = {p.category_id for p in product}
    existing_ids = {row[0] for row in db.query(Category.id).filter(Category.id.in_(category_ids)).all()}
    if category_ids - existing_ids:
        return False
    db.bulk_save_objects(db_products)
    db.commit()
    return db_products

def pagination_process(db:Session, page:int=1, limit:int=10):
    offset = (page-1)*limit
    products = db.query(Product).offset(offset).limit(limit).all()
    return products

def filter_products(
        db:Session, 
        category:str, 
        name:str | None = None, 
        min_price:int | None = None, 
        max_price:int | None = None, 
        limit:int=5, page:int=1
    ):
    stmt = db.query(Product).options(selectinload(Product.category))
    filters=[]
    if category:
        stmt = stmt.join(Product.category)
        filters.append(Category.name.ilike(f"%{category}%"))
    if name:
        filters.append(Product.name.ilike(f"%{name}%"))
    if min_price is not None:
        filters.append(Product.price>=min_price)
    if max_price is not None:
        filters.append(Product.price<=max_price)
    if filters:
        stmt = stmt.filter(*filters).distinct()
    offset=(page-1)*limit
    products=stmt.offset(offset).limit(limit).all()
    return products

# --- page-shaped reads (see idol_service.py's equivalent comment). Builds
# ProductCard-shaped dicts (schema/products.py) — every product-grid view
# (store grid, a group's products, a product's own recommendations) renders
# this same shape, assembled here in one pass instead of per-card lookups.

def _build_product_cards(db: Session, products: list[Product]):
    if not products:
        return []
    product_ids = [p.id for p in products]

    albums = db.query(AlbumDetail).filter(AlbumDetail.product_id.in_(product_ids)).all()
    album_by_product = {a.product_id: a for a in albums}

    merch = db.query(MerchDetail).filter(MerchDetail.product_id.in_(product_ids)).all()
    merch_by_product = {m.product_id: m for m in merch}

    album_genres = (
        db.query(AlbumGenre)
        .options(joinedload(AlbumGenre.genre))
        .filter(AlbumGenre.product_id.in_(product_ids))
        .all()
    )
    genres_by_product = {}
    for link in album_genres:
        genres_by_product.setdefault(link.product_id, []).append(link.genre)

    idols_by_id = {i.id: i for i in db.query(Idol).options(selectinload(Idol.color)).all()}
    groups_by_id = {g.id: g for g in db.query(Group).all()}
    # Longest-name-first so a group's name can't shadow one of its own
    # member's longer name — same heuristic the frontend used (catalogStore.
    # artistForAlbum) before this endpoint existed, kept only as a fallback
    # for plain merch with neither an album_details nor merch_details
    # row (a real idol/group FK, when one exists, always wins).
    name_candidates = sorted(
        [("idol", i) for i in idols_by_id.values()] + [("group", g) for g in groups_by_id.values()],
        key=lambda pair: len(pair[1].name), reverse=True,
    )

    def artist_ref(kind, entity):
        color_hex = entity.color.hex_code if kind == "idol" and getattr(entity, "color", None) else None
        return {"type": kind, "id": entity.id, "name": entity.name, "color_hex": color_hex}

    def resolve_artist(product, album, merch):
        for detail in (album, merch):
            if not detail:
                continue
            if detail.idol_id and detail.idol_id in idols_by_id:
                return artist_ref("idol", idols_by_id[detail.idol_id])
            if detail.group_id and detail.group_id in groups_by_id:
                return artist_ref("group", groups_by_id[detail.group_id])
        for kind, candidate in name_candidates:
            if product.name.startswith(candidate.name):
                return artist_ref(kind, candidate)
        return None

    cards = []
    for product in products:
        album = album_by_product.get(product.id)
        merch = merch_by_product.get(product.id)
        cards.append({
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "description": product.description,
            "quantity": product.quantity,
            "image_url": product.image_url,
            "category": product.category.name if product.category else None,
            "album": {
                "release_date": album.release_date,
                "track_count": album.track_count,
                "cover_image_url": album.cover_image_url,
            } if album else None,
            "genres": genres_by_product.get(product.id, []),
            "artist": resolve_artist(product, album, merch),
        })
    return cards

def get_store_page(db: Session):
    products = db.query(Product).options(joinedload(Product.category)).all()
    if not products:
        return False
    groups = db.query(Group).all()
    return {"products": _build_product_cards(db, products), "groups": groups}

def get_product_detail(db: Session, id: uuid.UUID):
    product = db.query(Product).options(joinedload(Product.category)).filter(Product.id == id).first()
    if not product:
        return False
    all_products = db.query(Product).options(joinedload(Product.category)).all()
    cards_by_id = {c["id"]: c for c in _build_product_cards(db, all_products)}
    card = cards_by_id[product.id]

    # Same-artist products (any type/category), plus — for album-family
    # items only — same-genre products, deduped and capped at 8. Mirrors
    # ProductDetailPage.vue's previous client-side recommendation logic.
    my_genre_ids = {genre.id for genre in card["genres"]}
    seen = {product.id}
    recommendations = []
    if card["artist"]:
        for other_id, other in cards_by_id.items():
            if other_id in seen:
                continue
            if other["artist"] and other["artist"]["type"] == card["artist"]["type"] and other["artist"]["id"] == card["artist"]["id"]:
                seen.add(other_id)
                recommendations.append(other)
    if card["album"] and my_genre_ids:
        for other_id, other in cards_by_id.items():
            if other_id in seen or not other["album"]:
                continue
            other_genre_ids = {genre.id for genre in other["genres"]}
            if my_genre_ids & other_genre_ids:
                seen.add(other_id)
                recommendations.append(other)

    return {"product": card, "recommendations": recommendations[:8]}

# --- manager/admin settings pages (see idol_service.py's equivalent
# comment — an empty list here is a normal state, not a 404). Plain
# ProductRead dicts, not the embedded ProductCard shape above — neither
# manager page renders album/genre/artist info, so album_details is never
# even queried here.

def _product_read_dict(product: Product):
    return {
        "id": product.id,
        "name": product.name,
        "price": product.price,
        "description": product.description,
        "quantity": product.quantity,
        "image_url": product.image_url,
        "category": product.category.name if product.category else None,
    }

# Batch version of _resolve_product_company_id — one query per detail table
# instead of two per product. A product with neither an album_details nor a
# merch_details row (plain merch) resolves to None: "no company owns
# this", not "belongs to no one's view" — _manager_scope_violation already
# treats that as manageable by any manager, so a manager's product list
# must show it too, not just their own company's products.
def _resolve_product_company_ids(db: Session, products: list[Product]):
    product_ids = [p.id for p in products]
    if not product_ids:
        return {}
    albums = db.query(AlbumDetail).filter(AlbumDetail.product_id.in_(product_ids)).all()
    merch = db.query(MerchDetail).filter(MerchDetail.product_id.in_(product_ids)).all()
    detail_by_product = {}
    for detail in albums + merch:
        detail_by_product[detail.product_id] = detail

    idol_ids = {d.idol_id for d in detail_by_product.values() if d.idol_id}
    group_ids = {d.group_id for d in detail_by_product.values() if d.group_id}
    idol_company = {i.id: i.company_id for i in db.query(Idol).filter(Idol.id.in_(idol_ids)).all()} if idol_ids else {}
    group_company = {g.id: g.company_id for g in db.query(Group).filter(Group.id.in_(group_ids)).all()} if group_ids else {}

    company_by_product = {}
    for product in products:
        detail = detail_by_product.get(product.id)
        if not detail:
            company_by_product[product.id] = None
        elif detail.idol_id:
            company_by_product[product.id] = idol_company.get(detail.idol_id)
        elif detail.group_id:
            company_by_product[product.id] = group_company.get(detail.group_id)
        else:
            company_by_product[product.id] = None
    return company_by_product

# company_id is optional: an admin (no single company of their own) passes
# none and sees every product; a manager passes their own company_id and
# sees that company's products plus every ownerless one (matching
# _manager_scope_violation's "ownerless = manageable by anyone" rule) —
# without this, a manager could see (and try to edit) another company's
# products and only find out it was forbidden after submitting the form.
def get_manager_products_page(db: Session, company_id: uuid.UUID | None = None):
    products = db.query(Product).options(joinedload(Product.category)).all()
    if company_id is not None:
        company_by_product = _resolve_product_company_ids(db, products)
        products = [p for p in products if company_by_product[p.id] in (None, company_id)]
    return {"products": [_product_read_dict(p) for p in products]}

def get_manager_product_form_page(db: Session, company_id: uuid.UUID | None = None):
    products = db.query(Product).options(joinedload(Product.category)).all()
    if company_id is not None:
        company_by_product = _resolve_product_company_ids(db, products)
        products = [p for p in products if company_by_product[p.id] in (None, company_id)]
    categories = db.query(Category).all()
    return {"products": [_product_read_dict(p) for p in products], "categories": categories}