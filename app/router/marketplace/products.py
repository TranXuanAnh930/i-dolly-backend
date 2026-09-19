import uuid
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.cache.cache_service import CacheService
from app.cache.rate_limit import ip_key, rate_limit
from app.db.models.identity import Users
from app.deps.auth import require_manager_or_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.marketplace import (
    ManagerProductFormPageRead,
    ManagerProductsPageRead,
    ProductCreate,
    ProductDetailRead,
    ProductRead,
    ProductSalesPageRead,
    ProductsPageRead,
    ProductWithCategoryRead,
    ProductWithDetailCreate,
    StorePageRead,
)
from app.services.marketplace.product_service import ProductService
from app.utils.storage import StorageError, get_storage

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/all", response_model=List[ProductRead])
async def list_of_existing_products(_:None=Depends(rate_limit(5,60,ip_key)), db:Session=Depends(get_db)) -> List[ProductRead]:
    db_products = CacheService.get_cached_products(db)
    if not db_products:
        raise HTTPException(status_code=404, detail="Products not found")
    return db_products

@router.get("/store-page", response_model=StorePageRead)
async def get_store_page_data(_:None=Depends(rate_limit(5,60,ip_key)),db: Session = Depends(get_db)) -> StorePageRead:
    result = CacheService.get_cached_store_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="Products not found")
    return result

@router.get("/{id}/detail", response_model=ProductDetailRead)
async def get_product_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)) -> ProductDetailRead:
    result = CacheService.get_cached_product_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    return result

@router.get("/manager-products-page", response_model=ManagerProductsPageRead)
async def get_manager_products_page_data(company_id: uuid.UUID | None = None, db: Session = Depends(get_db)) -> ManagerProductsPageRead:
    return CacheService.get_cached_manager_products_page(db, company_id)

@router.get("/manager-product-form-page", response_model=ManagerProductFormPageRead)
async def get_manager_product_form_page_data(company_id: uuid.UUID | None = None, db: Session = Depends(get_db)) -> ManagerProductFormPageRead:
    return CacheService.get_cached_manager_product_form_page(db, company_id)

@router.get("/{id}/sales", response_model=ProductSalesPageRead)
async def get_product_sales(
    id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    current_user: Users = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
) -> ProductSalesPageRead:
    try:
        return ProductService.get_product_sales_page(db, id, current_user, page, limit)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.get("/search/{id:uuid}", response_model=ProductWithCategoryRead)
async def search_existing_product(id:uuid.UUID, _:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)) -> ProductWithCategoryRead:
    db_product = ProductService.search_product(db, id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product

# multipart/form-data, not JSON — mirrors idols.py: an optional `image`
# file alongside the rest of the product fields in the same request.
# FastAPI can't mix a JSON body with Form/File fields on one endpoint, so
# this replaced the previous plain-JSON version; any client posting here
# now sends form fields, not a JSON body.
@router.post("/add_product", response_model=MessageResponse)
async def add_new_product(
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    quantity: int = Form(...),
    category_id: uuid.UUID = Form(...),
    image: UploadFile | None = File(None),
    current_user:Users=Depends(require_manager_or_admin),
    db:Session=Depends(get_db),
) -> MessageResponse:
    image_url = None
    if image is not None:
        try:
            image_url = await get_storage().save(image, subfolder="products")
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    product = ProductCreate(
        name=name, price=price, description=description, quantity=quantity,
        category_id=category_id, image_url=image_url,
    )
    try:
        ProductService.add_product(db, product)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_products()
    CacheService.delete_cached_manager_products_pages()
    CacheService.delete_cached_product_details()
    return MessageResponse(msg="Product added successfully")

# Bundles product creation with its AlbumDetail/MerchDetail row into one
# request (see ProductWithDetailCreate's own docstring for why) —
# ManagerProductFormPage.vue's "add product" form uses this, not the bare
# /add_product above, so a product created there always ends up attached to
# one of the manager's own idols/groups.
@router.post("/add_with_detail", response_model=MessageResponse)
async def add_new_product_with_detail(
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    quantity: int = Form(...),
    category_id: uuid.UUID = Form(...),
    detail_kind: str = Form(...),
    idol_id: uuid.UUID | None = Form(None),
    group_id: uuid.UUID | None = Form(None),
    release_date: date | None = Form(None),
    track_count: int | None = Form(None),
    format: str = Form("physical"),
    edition: str | None = Form(None),
    color_id: uuid.UUID | None = Form(None),
    image: UploadFile | None = File(None),
    current_user: Users = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
) -> MessageResponse:
    try:
        data = ProductWithDetailCreate(
            name=name, price=price, description=description, quantity=quantity,
            category_id=category_id, detail_kind=detail_kind, idol_id=idol_id, group_id=group_id,
            release_date=release_date, track_count=track_count, format=format,
            edition=edition, color_id=color_id,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    image_url = None
    if image is not None:
        try:
            image_url = await get_storage().save(image, subfolder="products")
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        ProductService.add_product_with_detail(db, data, image_url, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_products()
    CacheService.delete_cached_manager_products_pages()
    CacheService.delete_cached_product_details()
    return MessageResponse(msg="Product added successfully")

@router.put("/update/{id}", response_model=MessageResponse)
async def update_existing_product(id:uuid.UUID, product:ProductCreate, current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)) -> MessageResponse:
    try:
        ProductService.update_product(db, id, product, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_products()
    CacheService.delete_cached_manager_products_pages()
    CacheService.delete_cached_product_details()
    return MessageResponse(msg="Product Updated successfully")

@router.post("/{id}/image", response_model=MessageResponse)
async def upload_product_image(id:uuid.UUID, image: UploadFile = File(...), current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)) -> MessageResponse:
    """Replace an existing product's image without touching any other
    field — the complement to the inline upload on /products/add_product."""
    try:
        image_url = await get_storage().save(image, subfolder="products")
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        ProductService.set_product_image(db, id, image_url, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_products()
    CacheService.delete_cached_manager_products_pages()
    CacheService.delete_cached_product_details()
    return MessageResponse(msg="Product image updated successfully")

@router.delete("/delete/{id}", response_model=MessageResponse)
async def delete_existing_product(id:uuid.UUID, current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)) -> MessageResponse:
    try:
        ProductService.delete_product(db, id, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_products()
    CacheService.delete_cached_manager_products_pages()
    CacheService.delete_cached_product_details()
    return MessageResponse(msg="Product Deleted successfully")

@router.post("/bulk_products", response_model=MessageResponse)
async def add_new_bulk_products(product:List[ProductCreate], current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)) -> MessageResponse:
    try:
        db_product = ProductService.add_bulk_products(db, product)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    CacheService.delete_cached_products()
    CacheService.delete_cached_manager_products_pages()
    CacheService.delete_cached_product_details()
    return MessageResponse(msg=f"{len(db_product)} bulk products added successfully")

@router.get("/pagination", response_model=ProductsPageRead)
async def paginated_product(page:int=Query(1, ge=1), limit:int=Query(10, ge=1, le=50), db:Session=Depends(get_db)) -> ProductsPageRead:
    db_product = ProductService.pagination_process(db, page, limit)
    return ProductsPageRead(
        page=page,
        limit=limit,
        count=len(db_product),
        data=db_product,
    )

@router.get("/filter", response_model=ProductsPageRead)
async def filter_product(
    category:str,
    name:str | None = None,
    min_price:int | None = None,
    max_price:int | None = None,
    limit:int=Query(10, ge=1, le=50),
    page:int=Query(1, ge=1),
    db:Session=Depends(get_db)
    ) -> ProductsPageRead:
    products = ProductService.filter_products(db, category, name, min_price, max_price, limit, page)
    return ProductsPageRead(
        page=page,
        limit=limit,
        count=len(products),
        data=products,
    )
