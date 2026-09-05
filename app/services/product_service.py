import uuid
from sqlalchemy.orm import Session, selectinload, joinedload
from app.db.models.products import Product
from app.db.models.category import Category
from app.db.models.album_detail import AlbumDetail
from app.db.models.lightstick_detail import LightstickDetail
from app.db.models.genre import AlbumGenre
from app.db.models.idol import Idol
from app.db.models.group import Group
from app.db.models.user import Users
from app.schema.products import ProductRead, ProductCreate
from typing import List

# Company-scoping for update/delete/image-replace only (see docs/project_status.md
# SS4 item 10). A product has no company_id column of its own; its owner, if any,
# is resolved by whichever of album_details/lightstick_details references it -
# the same dual-FK "which row exists, then which of idol_id/group_id is set"
# lookup as album_detail_service._resolve_company_id / lightstick_detail_service's
# twin - rather than a direct column check, per docs/database-design.md SS6's
# note on this. A product tied to neither (plain merch not linked to any
# idol/group) has no company owner and stays manager-agnostic, matching the
# permissive behavior this project already had for every product before this -
# only a product actually tied to talent is scoped. add_product/add_bulk_products
# are deliberately NOT scoped: a bare Product row is created before any
# album_details/lightstick_details row exists to attach it to a company, so
# there is nothing to check yet at creation time - that's handled when the
# details row is created, by album_detail_service/lightstick_detail_service's
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
    lightstick = db.get(LightstickDetail, product_id)
    if lightstick:
        if lightstick.idol_id is not None:
            idol = db.get(Idol, lightstick.idol_id)
            return idol.company_id if idol else None
        if lightstick.group_id is not None:
            group = db.get(Group, lightstick.group_id)
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

    lightsticks = db.query(LightstickDetail).filter(LightstickDetail.product_id.in_(product_ids)).all()
    lightstick_by_product = {l.product_id: l for l in lightsticks}

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
    # for plain merch with neither an album_details nor lightstick_details
    # row (a real idol/group FK, when one exists, always wins).
    name_candidates = sorted(
        [("idol", i) for i in idols_by_id.values()] + [("group", g) for g in groups_by_id.values()],
        key=lambda pair: len(pair[1].name), reverse=True,
    )

    def artist_ref(kind, entity):
        color_hex = entity.color.hex_code if kind == "idol" and getattr(entity, "color", None) else None
        return {"type": kind, "id": entity.id, "name": entity.name, "color_hex": color_hex}

    def resolve_artist(product, album, lightstick):
        for detail in (album, lightstick):
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
        lightstick = lightstick_by_product.get(product.id)
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
            "artist": resolve_artist(product, album, lightstick),
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