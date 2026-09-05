import uuid
from sqlalchemy.orm import Session, selectinload
from app.db.models.products import Product
from app.db.models.category import Category
from app.db.models.album_detail import AlbumDetail
from app.db.models.lightstick_detail import LightstickDetail
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