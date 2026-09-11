import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile
from typing import List
from sqlalchemy.orm import Session
from app.cache.rate_limit import ip_key, rate_limit, user_key
from app.deps.db import get_db
from app.deps.auth import require_manager_or_admin
from app.schema.products import (
    ProductRead, ProductCreate, StorePageRead, ProductDetailRead,
    ManagerProductsPageRead, ManagerProductFormPageRead, ProductSalesPageRead,
)
from app.db.models.user import Users
from app.services.product_service import (
    add_product, search_product, update_product, delete_product, add_bulk_products, pagination_process, filter_products, set_product_image,
    get_store_page, get_product_detail, get_manager_products_page, get_manager_product_form_page, get_product_sales_page,
)
from app.cache.cache_service import get_cached_products, delete_cached_product
from app.cache.redis_client import redis_client
from app.utils.storage import get_storage, StorageError

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/all", response_model=List[ProductRead])
async def List_of_existing_products(_:None=Depends(rate_limit(5,60,ip_key)), db:Session=Depends(get_db)):
    db_products = get_cached_products(db)
    if not db_products:
        raise HTTPException(status_code=404, detail="Products not found")
    return db_products

@router.get("/store-page", response_model=StorePageRead)
async def get_store_page_data(db: Session = Depends(get_db)):
    result = get_store_page(db)
    if not result:
        raise HTTPException(status_code=404, detail="No products found")
    return result

@router.get("/{id}/detail", response_model=ProductDetailRead)
async def get_product_detail_by_id(id: uuid.UUID, db: Session = Depends(get_db)):
    result = get_product_detail(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    return result

@router.get("/manager-products-page", response_model=ManagerProductsPageRead)
async def get_manager_products_page_data(company_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return get_manager_products_page(db, company_id)

@router.get("/manager-product-form-page", response_model=ManagerProductFormPageRead)
async def get_manager_product_form_page_data(company_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return get_manager_product_form_page(db, company_id)

@router.get("/{id}/sales", response_model=ProductSalesPageRead)
async def get_product_sales(
    id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    current_user: Users = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
):
    result = get_product_sales_page(db, id, current_user, page, limit)
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only view sales for products belonging to their own company's idols/groups")
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Product not found")
    return result

@router.get("/search/{id:uuid}")
async def search_existing_product(id:uuid.UUID, _:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)):
    db_product = search_product(db, id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product

# multipart/form-data, not JSON — mirrors idols.py: an optional `image`
# file alongside the rest of the product fields in the same request.
# FastAPI can't mix a JSON body with Form/File fields on one endpoint, so
# this replaced the previous plain-JSON version; any client posting here
# now sends form fields, not a JSON body.
@router.post("/add_product")
async def add_new_product(
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    quantity: int = Form(...),
    category_id: uuid.UUID = Form(...),
    image: UploadFile | None = File(None),
    current_user:Users=Depends(require_manager_or_admin),
    db:Session=Depends(get_db),
):
    image_url = None
    if image is not None:
        try:
            image_url = await get_storage().save(image, subfolder="products")
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e))

    product = ProductCreate(
        name=name, price=price, description=description, quantity=quantity,
        category_id=category_id, image_url=image_url,
    )
    db_product = add_product(db, product)
    if not db_product:
        raise HTTPException(status_code=400, detail="Unable to add product")
    redis_client.delete("products:list")
    return {"msg" : "Product added successfully"}

@router.put("/update/{id}")
async def update_existing_product(id:uuid.UUID, product:ProductCreate, current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)):
    db_product = update_product(db, id, product, current_user)
    if db_product == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage products belonging to their own company's idols/groups")
    if db_product == "category_not_found":
        raise HTTPException(status_code=400, detail="category_id does not reference an existing category")
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    delete_cached_product(id)
    return {"msg" : "Product Updated successfully"}

@router.post("/{id}/image")
async def upload_product_image(id:uuid.UUID, image: UploadFile = File(...), current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)):
    """Replace an existing product's image without touching any other
    field — the complement to the inline upload on /products/add_product."""
    try:
        image_url = await get_storage().save(image, subfolder="products")
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db_product = set_product_image(db, id, image_url, current_user)
    if db_product == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage products belonging to their own company's idols/groups")
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    delete_cached_product(id)
    return {"msg" : "Product image updated successfully"}

@router.delete("/delete/{id}")
async def delete_existing_product(id:uuid.UUID, current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)):
    db_product = delete_product(db, id, current_user)
    if db_product == "forbidden":
        raise HTTPException(status_code=403, detail="Managers can only manage products belonging to their own company's idols/groups")
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    delete_cached_product(id)
    return {"detail" : "Product Deleted successfully"}

@router.post("/bulk_products")
async def add_new_bulk_products(product:List[ProductCreate], current_user:Users=Depends(require_manager_or_admin), db:Session=Depends(get_db)):
    db_product = add_bulk_products(db, product)
    if not db_product:
        raise HTTPException(status_code=400, detail="Unable to add products")
    redis_client.delete("products:list")
    return {"msg" : f"{len(db_product)} bulk products added successfully"}

@router.get("/pagination")
async def paginated_product(page:int=Query(1, ge=1), limit:int=Query(10, ge=1, le=50), db:Session=Depends(get_db)):
    db_product = pagination_process(db, page, limit)
    return {
        "page":page,
        "limit":limit,
        "count":len(db_product),
        "data":db_product
    }

@router.get("/filter")
async def filter_product(
    category:str,
    name:str | None = None,
    min_price:int | None = None,
    max_price:int | None = None,
    limit:int=Query(10, ge=1, le=50),
    page:int=Query(1, ge=1),
    db:Session=Depends(get_db)
    ):
    products = filter_products(db, category, name, min_price, max_price, limit, page)
    return {
        "page":page,
        "limit":limit,
        "count":len(products),
        "data":products
    }
