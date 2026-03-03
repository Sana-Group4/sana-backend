from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from db import get_db
from models import Item, User, Activity, CoachLink, UserType, Biometric, BiometricType
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

class ClientBasicInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    firstName: str
    lastName: str
    email: str | None = None
    phone: int | None = None
    profilePictureUrl: str | None = None  

class BiometricVectorIn(BaseModel):
    user_id: int
    biometric_type: BiometricType
    times: list[datetime]                 
    values: list[float]       

class BiometricVectorOut(BaseModel):
    user_id: int
    biometric_type: BiometricType
    t: list[datetime]
    y: list[float | int | None]

          


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

@router.post("/activities", response_model=ActivityResponse)
async def create_activity(
    activity: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user)
):
    """Create a new activity for the current user."""
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

@router.get("/coach/clients", response_model=list[ClientBasicInfo])
async def get_coach_clients(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if user.userType != UserType.COACH:
        raise HTTPException(status_code=403, detail="Only coaches can access this endpoint")

    stmt = (
        select(User)
        .join(CoachLink, CoachLink.client_id == User.id)
        .where(CoachLink.coach_id == user.id)
        .order_by(User.lastName, User.firstName)
    )

    clients = (await db.scalars(stmt)).all()
    return clients

async def assert_can_access_user_data(
    db: AsyncSession,
    current_user: User,
    target_user_id: int,
) -> None:
    if current_user.userType == UserType.CLIENT:
        if target_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Clients can only access their own data")
        return

    if current_user.userType == UserType.COACH:
        if target_user_id == current_user.id:
            return
        link_stmt = select(CoachLink).where(
            CoachLink.coach_id == current_user.id,
            CoachLink.client_id == target_user_id,
        )
        link = (await db.execute(link_stmt)).scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=403, detail="Not your client")
        return

    raise HTTPException(status_code=403, detail="Forbidden")

@router.post("/biometrics/vector")
async def store_biometric_vector(
    body: BiometricVectorIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if len(body.times) != len(body.values):
        raise HTTPException(status_code=400, detail="times and values must have the same length")
    if not body.times:
        raise HTTPException(status_code=400, detail="times/values cannot be empty")

    await assert_can_access_user_data(db, user, body.user_id)

    rows: list[Biometric] = []
    for t, v in zip(body.times, body.values):
        rows.append(
            Biometric(
                user_id=body.user_id,
                biometric_type=body.biometric_type,
                recorded_at=t,
                value_float=float(v),
                value_int=None,
            )
        )

    db.add_all(rows)
    await db.commit()
    return {"inserted": len(rows)}

@router.get("/biometrics/vector", response_model=BiometricVectorOut)
async def get_biometric_vector(
    user_id: int,
    biometric_type: BiometricType,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await assert_can_access_user_data(db, user, user_id)

    stmt = (
        select(Biometric)
        .where(
            Biometric.user_id == user_id,
            Biometric.biometric_type == biometric_type,
            Biometric.recorded_at >= start,
            Biometric.recorded_at <= end,
        )
        .order_by(Biometric.recorded_at.asc())
    )
    rows = (await db.scalars(stmt)).all()

    return {
        "user_id": user_id,
        "biometric_type": biometric_type,
        "t": [r.recorded_at for r in rows],
        "y": [r.value_float if r.value_float is not None else r.value_int for r in rows],
    }