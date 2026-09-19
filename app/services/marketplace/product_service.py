import uuid
from typing import Any, List, Literal

from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models.identity import Users
from app.db.models.marketplace import AlbumDetail, AlbumGenre, Category, MerchDetail, Order, OrderItem, Product
from app.db.models.talent import Group, Idol, IdolColor
from app.exception.db_triggers import commit_or_raise, flush_or_raise
from app.schema.marketplace import ProductCreate, ProductRead, ProductWithDetailCreate
from app.utils.resale import RESALE_CAP_QUANTITY


class ProductService:

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

    @staticmethod
    def _resolve_product_company_id(db: Session, product_id: uuid.UUID) -> uuid.UUID | None:
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

    @staticmethod
    def _manager_scope_violation(db: Session, current_user: Users, product_id: uuid.UUID) -> bool:
        if current_user.role != "manager":
            return False
        company_id = ProductService._resolve_product_company_id(db, product_id)
        if company_id is None:
            return False  # ownerless product - any manager may manage it
        return current_user.company_id != company_id

    @staticmethod
    def list_of_products(db:Session) -> list[Product] | Literal[False]:
        db_products = db.query(Product).options(selectinload(Product.category)).all()
        if not db_products:
            return False
        return db_products

    @staticmethod
    def search_product(db:Session, id:uuid.UUID) -> dict[str, Any] | Literal[False]:
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

    @staticmethod
    def add_product(db: Session, product:ProductCreate) -> Product | Literal[False]:
        if not db.get(Category, product.category_id):
            return False  # invalid category_id — was an uncaught IntegrityError -> 500 at commit
        db_product = Product(**product.model_dump())
        db.add(db_product)
        db.commit()
        db.refresh(db_product)
        return db_product

    # Same "which FK is set, then resolve its owner" shape as
    # album_detail_service/merch_detail_service's own _resolve_company_id /
    # _artist_active_or_missing — duplicated locally rather than importing
    # another module's private helpers, matching this project's existing
    # convention of a small scoping helper per service file (concert_service,
    # ticket_type_service, lottery_campaign_service all do the same).
    @staticmethod
    def _resolve_owner_company_id(db: Session, idol_id: uuid.UUID | None, group_id: uuid.UUID | None) -> uuid.UUID | None:
        if idol_id is not None:
            idol = db.get(Idol, idol_id)
            return idol.company_id if idol else None
        if group_id is not None:
            group = db.get(Group, group_id)
            return group.company_id if group else None
        return None

    @staticmethod
    def _owner_active_or_missing(db: Session, idol_id: uuid.UUID | None, group_id: uuid.UUID | None) -> bool:
        if idol_id is not None:
            idol = db.get(Idol, idol_id)
            return idol is None or idol.is_active
        if group_id is not None:
            group = db.get(Group, group_id)
            return group is None or group.is_active
        return True

    # The combined create ManagerProductFormPage.vue actually uses — creates
    # the Product and its AlbumDetail/MerchDetail row in one transaction (flush
    # for the product's generated id, one commit for both), so a rejected
    # detail (bad owner, wrong company, ...) rolls the product insert back too.
    # Unlike the bare add_product above (deliberately unscoped — see this
    # module's top comment), this is scoped from the start: the schema itself
    # requires idol_id/group_id, so there's always an owner to check against.
    @staticmethod
    def add_product_with_detail(db: Session, data: ProductWithDetailCreate, image_url: str | None, current_user: Users) -> Product | Literal["category_not_found", "owner_not_found", "artist_inactive", "forbidden"]:
        if not db.get(Category, data.category_id):
            return "category_not_found"
        if data.idol_id is not None and not db.get(Idol, data.idol_id):
            return "owner_not_found"
        if data.group_id is not None and not db.get(Group, data.group_id):
            return "owner_not_found"
        if data.detail_kind == "merch" and data.color_id is not None and not db.get(IdolColor, data.color_id):
            return "owner_not_found"
        if not ProductService._owner_active_or_missing(db, data.idol_id, data.group_id):
            return "artist_inactive"

        owner_company_id = ProductService._resolve_owner_company_id(db, data.idol_id, data.group_id)
        if current_user.role == "manager" and current_user.company_id != owner_company_id:
            return "forbidden"

        db_product = Product(
            name=data.name, price=data.price, description=data.description,
            quantity=data.quantity, category_id=data.category_id, image_url=image_url,
        )
        db.add(db_product)
        flush_or_raise(db)  # populates db_product.id for the detail row below, same transaction

        if data.detail_kind == "album":
            db_detail = AlbumDetail(
                product_id=db_product.id, idol_id=data.idol_id, group_id=data.group_id,
                release_date=data.release_date, track_count=data.track_count, format=data.format,
            )
        else:
            db_detail = MerchDetail(
                product_id=db_product.id, idol_id=data.idol_id, group_id=data.group_id,
                edition=data.edition, color_id=data.color_id,
            )
        db.add(db_detail)
        commit_or_raise(db)  # one commit for both rows — a rejected detail rolls the product back too
        db.refresh(db_product)
        return db_product

    @staticmethod
    def update_product(db:Session, id:uuid.UUID, product:ProductCreate, current_user:Users) -> Product | Literal[False, "forbidden", "price_locked", "category_not_found"]:
        db_product = db.get(Product, id)
        if not db_product:
            return False
        if ProductService._manager_scope_violation(db, current_user, id):
            return "forbidden"
        # Managers can't reprice a product after creation, same rationale as
        # ticket_type_service.update_ticket_type — only an admin can correct it.
        if current_user.role == "manager" and round(product.price, 2) != round(db_product.price, 2):
            return "price_locked"
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

    @staticmethod
    def set_product_image(db: Session, id: uuid.UUID, image_url: str, current_user: Users) -> Product | Literal[False, "forbidden"]:
        """Used by the dedicated /products/{id}/image upload endpoint — updates
        only the image, leaving every other field untouched (unlike
        update_product, which replaces the whole row from a ProductCreate)."""
        db_product = db.get(Product, id)
        if not db_product:
            return False
        if ProductService._manager_scope_violation(db, current_user, id):
            return "forbidden"
        db_product.image_url = image_url
        db.commit()
        db.refresh(db_product)
        return db_product

    @staticmethod
    def delete_product(db:Session, id: uuid.UUID, current_user: Users) -> Product | Literal[False, "forbidden"]:
        db_product = db.get(Product, id)
        if not db_product:
            return False
        if ProductService._manager_scope_violation(db, current_user, id):
            return "forbidden"
        db.delete(db_product)
        db.commit()
        return db_product

    @staticmethod
    def add_bulk_products(db:Session, product:List[ProductRead]) -> list[Product] | Literal[False]:
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

    @staticmethod
    def pagination_process(db:Session, page:int=1, limit:int=10) -> list[Product]:
        offset = (page-1)*limit
        products = db.query(Product).offset(offset).limit(limit).all()
        return products

    @staticmethod
    def filter_products(
            db:Session, 
            category:str, 
            name:str | None = None, 
            min_price:int | None = None, 
            max_price:int | None = None, 
            limit:int=5, page:int=1
        ) -> list[Product]:
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

    @staticmethod
    def _build_product_cards(db: Session, products: list[Product]) -> list[dict[str, Any]]:
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

        def artist_ref(kind: Literal["idol", "group"], entity: Idol | Group) -> dict[str, Any]:
            color_hex = entity.color.hex_code if kind == "idol" and getattr(entity, "color", None) else None
            return {"type": kind, "id": entity.id, "name": entity.name, "color_hex": color_hex}

        def resolve_artist(product: Product, album: AlbumDetail | None, merch: MerchDetail | None) -> dict[str, Any] | None:
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
                "resale_cap_quantity": RESALE_CAP_QUANTITY if (product.category and product.category.is_resale_capped) else None,
                "album": {
                    "release_date": album.release_date,
                    "track_count": album.track_count,
                    "cover_image_url": album.cover_image_url,
                } if album else None,
                "genres": genres_by_product.get(product.id, []),
                "artist": resolve_artist(product, album, merch),
            })
        return cards

    @staticmethod
    def get_store_page(db: Session) -> dict[str, Any] | Literal[False]:
        products = db.query(Product).options(joinedload(Product.category)).all()
        if not products:
            return False
        groups = db.query(Group).all()
        return {"products": ProductService._build_product_cards(db, products), "groups": groups}

    @staticmethod
    def get_product_detail(db: Session, id: uuid.UUID) -> dict[str, Any] | Literal[False]:
        product = db.query(Product).options(joinedload(Product.category)).filter(Product.id == id).first()
        if not product:
            return False
        all_products = db.query(Product).options(joinedload(Product.category)).all()
        cards_by_id = {c["id"]: c for c in ProductService._build_product_cards(db, all_products)}
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

    @staticmethod
    def _product_read_dict(product: Product) -> dict[str, Any]:
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
    # must show it too, not just their own company's products. Not
    # underscore-prefixed (unlike its singular sibling above): order_service's
    # get_manager_orders_page reuses it to scope orders by which products in
    # them belong to a company, the same "which detail row, then which of
    # idol_id/group_id" chain.
    @staticmethod
    def resolve_product_company_ids(db: Session, products: list[Product]) -> dict[uuid.UUID, uuid.UUID | None]:
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
    @staticmethod
    def get_manager_products_page(db: Session, company_id: uuid.UUID | None = None) -> dict[str, Any]:
        products = db.query(Product).options(joinedload(Product.category)).all()
        if company_id is not None:
            company_by_product = ProductService.resolve_product_company_ids(db, products)
            products = [p for p in products if company_by_product[p.id] in (None, company_id)]
        return {"products": [ProductService._product_read_dict(p) for p in products]}

    @staticmethod
    def get_manager_product_form_page(db: Session, company_id: uuid.UUID | None = None) -> dict[str, Any]:
        products = db.query(Product).options(joinedload(Product.category)).all()
        if company_id is not None:
            company_by_product = ProductService.resolve_product_company_ids(db, products)
            products = [p for p in products if company_by_product[p.id] in (None, company_id)]
        categories = db.query(Category).all()
        # idols/groups/colors are for the "attach this product to one of my own
        # idols/groups" step of creating a product (add_product_with_detail) —
        # every idol/group is returned (not company-filtered server-side) since
        # an admin's form needs every company's, same as ManagerIdolFormPageRead's
        # own groups field; the manager form filters client-side by company_id.
        idols = db.query(Idol).all()
        groups = db.query(Group).all()
        colors = db.query(IdolColor).all()
        return {
            "products": [ProductService._product_read_dict(p) for p in products],
            "categories": categories,
            "idols": idols,
            "groups": groups,
            "colors": colors,
        }

    # --- sales history — replaces the manager products page's old hard-delete
    # action (deleting a Product with any order history would CASCADE-delete
    # its orders_items rows, same class of data-loss bug the concert/idol/group
    # soft-deletes already fixed). "Delete" isn't replaced with a soft-delete
    # here since Product has nothing to flip (no is_active/status column) —
    # instead the manager UI drops the destructive action entirely in favor of
    # a read-only view of what actually sold, paginated newest-first same as
    # /products/pagination's page/limit/count/data shape.
    @staticmethod
    def get_product_sales_page(db: Session, product_id: uuid.UUID, current_user: Users, page: int = 1, limit: int = 10) -> dict[str, Any] | Literal["not_found", "forbidden"]:
        db_product = db.get(Product, product_id)
        if not db_product:
            return "not_found"
        if ProductService._manager_scope_violation(db, current_user, product_id):
            return "forbidden"

        query = (
            db.query(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .filter(OrderItem.product_id == product_id)
            .options(joinedload(OrderItem.order))
            .order_by(Order.created_at.desc())
        )
        offset = (page - 1) * limit
        rows = query.offset(offset).limit(limit).all()

        data = [
            {
                "order_id": item.order_id,
                "order_status": item.order.status,
                "order_created_at": item.order.created_at,
                "quantity": item.quantity,
                "price": item.price,
                "line_total": item.price * item.quantity,
            }
            for item in rows
        ]
        return {"page": page, "limit": limit, "count": len(data), "data": data}
