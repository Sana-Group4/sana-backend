from fastapi import APIRouter, Depends, HTTPException, status, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload


from pydantic import BaseModel, ConfigDict

from db import get_db
from models import Item, User, CoachLink, Activity, UserType
from api.auth import get_current_active_user, Token

class SafeUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: str
    firstName: str
    lastName: str
    username: str

class ActivityCreate(BaseModel):
    name: str
    description: str

class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    user_id: int

class UserUpdatable(BaseModel):
    email: str | None
    phone: int | None
    lastName: str | None
    firstName: str | None
    #note: UploadFile contains: filename, content_type, file
    profilePic: UploadFile | None



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


#gets basic account info from access
@router.get("/account", response_model=SafeUser)
async def get_account(user: User = Depends(get_current_active_user)):
    return user

@router.post("/update_account")
async def update_account(user: User = Depends(get_current_active_user), data = Depends(UserUpdatable)):

    
    pass     

@router.post("/activities", response_model=ActivityResponse)
async def create_activity(
    activity: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    assigned_to: int| None = None
):
    new_activity

    if assigned_to & user.userType == UserType.COACH:
        """Ensure coach is the coach of the client being assigned, if so we create the activity"""
        query = (
            select(CoachLink)
            .where(and_(CoachLink.client_id == assigned_to, CoachLink.coach_id == user.id))
        )
        client = await db.execute(query)
        client = client.scalars().first()
        if not client:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="cannot assign activity. userId provided is not valid")
        
        new_activity = Activity(
            name = activity.name,
            description = activity.description,
            user_id = client.client_id
        )
    else:
        """Create a new activity for the current user. (self assigned)"""
        new_activity = Activity(
            name=activity.name,
            description=activity.description,
            user_id=user.id
        )

    db.add(new_activity)
    await db.commit()
    await db.refresh(new_activity)
    return new_activity

@router.get("/activities", response_model=list[ActivityResponse])
async def get_activities(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user)
):
    """Get all activities for the current user."""
    result = await db.execute(
        select(Activity).where(Activity.user_id == user.id)
    )
    return result.scalars().all()
    