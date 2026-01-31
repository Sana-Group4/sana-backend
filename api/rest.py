from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pydantic import BaseModel, ConfigDict

from db import get_db
from models import Item
from models import User
from api.auth import get_current_active_user, Token

class SafeUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: str
    firstName: str
    lastName: str
    username: str


router = APIRouter(prefix="/api")

@router.post("/items")
async def create_item(name: str, db: AsyncSession = Depends(get_db)):
    item = Item(name=name)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"id": item.id, "name": item.name}

@router.get("/items")
async def list_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Item))
    return [{"id": i.id, "name": i.name} for i in result.scalars().all()]


#gets basic account into from access
@router.get("/account", response_model=SafeUser)
async def get_account(user: User = Depends(get_current_active_user)):
    return user
    