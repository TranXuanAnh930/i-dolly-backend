from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

class User(BaseModel): 
    name : str = Field(..., min_length=1, max_length=100)
    email : EmailStr

class UserCreate(User):
    password : str = Field(..., min_length=6, max_length=128)

class UserOut(User):
    id : int
    is_active : bool = True
    is_admin : bool = False
    is_verified : bool = False
    created_at : datetime 
    updated_at : datetime

class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class SetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)

class MakeAdminRequest(BaseModel):
    user_id: int
