from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db import get_db
from models import Item

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