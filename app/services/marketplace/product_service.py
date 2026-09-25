import uuid
from typing import List, Literal

from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models.identity import Users
from app.db.models.marketplace import AlbumDetail, AlbumGenre, Category, MerchDetail, Order, OrderItem, Product
from app.db.models.talent import Group, Idol, IdolColor
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import commit_or_raise, flush_or_raise
from app.schema.identity import UserRole
from app.schema.marketplace import (
    AlbumMini,
    ArtistRef,
    ManagerProductFormPageRead,
    ManagerProductsPageRead,
    ProductCard,
    ProductCreate,
    ProductDetailRead,
    ProductRead,
    ProductSaleRead,
    ProductSalesPageRead,
    ProductWithCategoryRead,
    ProductWithDetailCreate,
    StorePageRead,
)
from app.utils.resale import RESALE_CAP_QUANTITY


class ProductService:

    # Company scoping for update/delete/image: a product's owner is resolved through its
    # album_details or merch_details row. Products with neither are ownerless and any manager
    # may manage them.

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
        if current_user.role != UserRole.manager:
            return False
        company_id = ProductService._resolve_product_company_id(db, product_id)
        if company_id is None:
            return False  # ownerless product - any manager may manage it
        return current_user.company_id != company_id

    @staticmethod
    def list_of_products(db:Session) -> list[Product]:
        return db.query(Product).options(selectinload(Product.category)).all()

    @staticmethod
    def search_product(db:Session, id:uuid.UUID) -> ProductWithCategoryRead | None:
        db_product = db.query(Product).options(selectinload(Product.category)).filter(Product.id==id).first()
        if not db_product:
            return None
        return ProductWithCategoryRead(
            id=db_product.id,
            name=db_product.name,
            price=db_product.price,
            description=db_product.description,
            quantity=db_product.quantity,
            image_url=db_product.image_url,
            category=db_product.category,
        )

    @staticmethod
    def add_product(db: Session, product:ProductCreate) -> Product:
        if not db.get(Category, product.category_id):
            raise NotFoundError("category_id does not reference an existing category")
        db_product = Product(**product.model_dump())
        db.add(db_product)
        db.commit()
        db.refresh(db_product)
        return db_product

    # Resolve the owning company from an idol_id or group_id.
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

    # Creates the Product and its AlbumDetail/MerchDetail row in one transaction, so a rejected
    # detail rolls back the product too.
    @staticmethod
    def add_product_with_detail(db: Session, data: ProductWithDetailCreate, image_url: str | None, current_user: Users) -> Product:
        if not db.get(Category, data.category_id):
            raise NotFoundError("category_id does not reference an existing category")
        if data.idol_id is not None and not db.get(Idol, data.idol_id):
            raise NotFoundError("idol_id, group_id, or color_id does not reference an existing record")
        if data.group_id is not None and not db.get(Group, data.group_id):
            raise NotFoundError("idol_id, group_id, or color_id does not reference an existing record")
        if data.detail_kind == "merch" and data.color_id is not None and not db.get(IdolColor, data.color_id):
            raise NotFoundError("idol_id, group_id, or color_id does not reference an existing record")
        if not ProductService._owner_active_or_missing(db, data.idol_id, data.group_id):
            raise BadRequestError("Cannot attach a new product to a deactivated idol/group")

        owner_company_id = ProductService._resolve_owner_company_id(db, data.idol_id, data.group_id)
        if current_user.role == UserRole.manager and current_user.company_id != owner_company_id:
            raise ForbiddenError("Managers can only create products for their own company's idols/groups")

        db_product = Product(
            name=data.name, price=data.price, description=data.description,
            quantity=data.quantity, category_id=data.category_id, image_url=image_url,
        )
        db.add(db_product)
        flush_or_raise(db)  # populates db_product.id for the detail row

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
        commit_or_raise(db)
        db.refresh(db_product)
        return db_product

    @staticmethod
    def update_product(db:Session, id:uuid.UUID, product:ProductCreate, current_user:Users) -> Product:
        db_product = db.get(Product, id)
        if not db_product:
            raise NotFoundError("Product not found")
        if ProductService._manager_scope_violation(db, current_user, id):
            raise ForbiddenError("Managers can only manage products belonging to their own company's idols/groups")
        # Only admins can change a product's price after creation.
        if current_user.role == UserRole.manager and round(product.price, 2) != round(db_product.price, 2):
            raise ForbiddenError("Managers cannot change product price after creation — ask an admin")
        if not db.get(Category, product.category_id):
            raise NotFoundError("category_id does not reference an existing category")
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
    def set_product_image(db: Session, id: uuid.UUID, image_url: str, current_user: Users) -> Product:
        """Replace only the product's image URL."""
        db_product = db.get(Product, id)
        if not db_product:
            raise NotFoundError("Product not found")
        if ProductService._manager_scope_violation(db, current_user, id):
            raise ForbiddenError("Managers can only manage products belonging to their own company's idols/groups")
        db_product.image_url = image_url
        db.commit()
        db.refresh(db_product)
        return db_product

    @staticmethod
    def delete_product(db:Session, id: uuid.UUID, current_user: Users) -> Product:
        db_product = db.get(Product, id)
        if not db_product:
            raise NotFoundError("Product not found")
        if ProductService._manager_scope_violation(db, current_user, id):
            raise ForbiddenError("Managers can only manage products belonging to their own company's idols/groups")
        db.delete(db_product)
        db.commit()
        return db_product

    @staticmethod
    def add_bulk_products(db:Session, product:List[ProductCreate]) -> list[Product]:
        if not product:
            raise BadRequestError("No products given")
        db_products = [Product(**p.model_dump()) for p in product]
        # Validate every category before saving any product (all-or-nothing).
        category_ids = {p.category_id for p in product}
        existing_ids = {row[0] for row in db.query(Category.id).filter(Category.id.in_(category_ids)).all()}
        if category_ids - existing_ids:
            raise NotFoundError("One or more category_id values do not reference an existing category")
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

    # --- page-shaped reads. Builds the ProductCard shape used by every product grid in one pass.

    @staticmethod
    def _build_product_cards(db: Session, products: list[Product]) -> list[ProductCard]:
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
        # Name-matching fallback for products with no album/merch detail: longest name first so a
        # group name doesn't shadow a member's longer name.
        name_candidates = sorted(
            [("idol", i) for i in idols_by_id.values()] + [("group", g) for g in groups_by_id.values()],
            key=lambda pair: len(pair[1].name), reverse=True,
        )

        def artist_ref(kind: Literal["idol", "group"], entity: Idol | Group) -> ArtistRef:
            color_hex = entity.color.hex_code if kind == "idol" and getattr(entity, "color", None) else None
            return ArtistRef(type=kind, id=entity.id, name=entity.name, color_hex=color_hex)

        def resolve_artist(product: Product, album: AlbumDetail | None, merch: MerchDetail | None) -> ArtistRef | None:
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
            cards.append(ProductCard(
                id=product.id,
                name=product.name,
                price=product.price,
                description=product.description,
                quantity=product.quantity,
                image_url=product.image_url,
                category=product.category.name if product.category else None,
                resale_cap_quantity=RESALE_CAP_QUANTITY if (product.category and product.category.is_resale_capped) else None,
                album=AlbumMini(
                    release_date=album.release_date,
                    track_count=album.track_count,
                ) if album else None,
                genres=genres_by_product.get(product.id, []),
                artist=resolve_artist(product, album, merch),
            ))
        return cards

    @staticmethod
    def get_store_page(db: Session) -> StorePageRead | None:
        products = db.query(Product).options(joinedload(Product.category)).all()
        if not products:
            return None
        groups = db.query(Group).all()
        return StorePageRead(products=ProductService._build_product_cards(db, products), groups=groups)

    @staticmethod
    def get_product_detail(db: Session, id: uuid.UUID) -> ProductDetailRead | None:
        product = db.query(Product).options(joinedload(Product.category)).filter(Product.id == id).first()
        if not product:
            return None
        all_products = db.query(Product).options(joinedload(Product.category)).all()
        cards_by_id = {c.id: c for c in ProductService._build_product_cards(db, all_products)}
        card = cards_by_id[product.id]

        # Same-artist products, plus same-genre products for albums; deduped, max 8.
        my_genre_ids = {genre.id for genre in card.genres}
        seen = {product.id}
        recommendations = []
        if card.artist:
            for other_id, other in cards_by_id.items():
                if other_id in seen:
                    continue
                if other.artist and other.artist.type == card.artist.type and other.artist.id == card.artist.id:
                    seen.add(other_id)
                    recommendations.append(other)
        if card.album and my_genre_ids:
            for other_id, other in cards_by_id.items():
                if other_id in seen or not other.album:
                    continue
                other_genre_ids = {genre.id for genre in other.genres}
                if my_genre_ids & other_genre_ids:
                    seen.add(other_id)
                    recommendations.append(other)

        return ProductDetailRead(product=card, recommendations=recommendations[:8])

    # --- manager/admin settings pages (an empty list is a normal result, not a 404). Returns plain
    # ProductRead dicts; these pages don't need album/genre/artist data.

    @staticmethod
    def _product_read_dict(product: Product) -> ProductRead:
        return ProductRead(
            id=product.id,
            name=product.name,
            price=product.price,
            description=product.description,
            quantity=product.quantity,
            image_url=product.image_url,
            category=product.category.name if product.category else None,
        )

    # Batch version of _resolve_product_company_id: one query per detail table. Also used by
    # order_service.
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

    # company_id=None (admin) returns every product; a manager's company_id returns that
    # company's products plus ownerless ones.
    @staticmethod
    def get_manager_products_page(db: Session, company_id: uuid.UUID | None = None) -> ManagerProductsPageRead:
        products = db.query(Product).options(joinedload(Product.category)).all()
        if company_id is not None:
            company_by_product = ProductService.resolve_product_company_ids(db, products)
            products = [p for p in products if company_by_product[p.id] in (None, company_id)]
        return ManagerProductsPageRead(products=[ProductService._product_read_dict(p) for p in products])

    @staticmethod
    def get_manager_product_form_page(db: Session, company_id: uuid.UUID | None = None) -> ManagerProductFormPageRead:
        products = db.query(Product).options(joinedload(Product.category)).all()
        if company_id is not None:
            company_by_product = ProductService.resolve_product_company_ids(db, products)
            products = [p for p in products if company_by_product[p.id] in (None, company_id)]
        categories = db.query(Category).all()
        # Every idol/group is returned so admins can pick any company; the manager form filters
        # client-side by company_id.
        idols = db.query(Idol).all()
        groups = db.query(Group).all()
        colors = db.query(IdolColor).all()
        return ManagerProductFormPageRead(
            products=[ProductService._product_read_dict(p) for p in products],
            categories=categories,
            idols=idols,
            groups=groups,
            colors=colors,
        )

    # --- sales history: read-only view of a product's order items.
    @staticmethod
    def get_product_sales_page(db: Session, product_id: uuid.UUID, current_user: Users, page: int = 1, limit: int = 10) -> ProductSalesPageRead:
        db_product = db.get(Product, product_id)
        if not db_product:
            raise NotFoundError("Product not found")
        if ProductService._manager_scope_violation(db, current_user, product_id):
            raise ForbiddenError("Managers can only view sales for products belonging to their own company's idols/groups")

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
            ProductSaleRead(
                order_id=item.order_id,
                order_status=item.order.status,
                order_created_at=item.order.created_at,
                quantity=item.quantity,
                price=item.price,
                line_total=item.price * item.quantity,
            )
            for item in rows
        ]
        return ProductSalesPageRead(page=page, limit=limit, count=len(data), data=data)
