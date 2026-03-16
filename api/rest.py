from fastapi import APIRouter, Depends, HTTPException, status, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime
from sqlalchemy.orm import selectinload


from pydantic import BaseModel, ConfigDict

from db import get_db
from models import Item, User, CoachLink, Activity, Biometric, BiometricType, ActivityType, ActivityStatus
from api.auth import get_current_active_user, Token

class SafeUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: str
    phone: int | None = None
    firstName: str
    lastName: str
    username: str

class ActivityCreate(BaseModel):
    name: str
    description: str
    activity_type: ActivityType = ActivityType.CUSTOM
    target_value: float | None = None
    unit: str | None = None
    due_at: datetime | None = None

class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    user_id: int
    assigned_by_id: int
    assigned_by_coach: bool

    activity_type: ActivityType
    target_value: float | None
    progress_value: float
    unit: str | None
    assigned_at: datetime
    due_at: datetime | None
    status: ActivityStatus


class UserUpdatable(BaseModel):
    email: str | None = None
    phone: int | None = None
    lastName: str | None = None
    firstName: str | None = None

class ClientBasicInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    firstName: str
    lastName: str
    email: str | None = None
    phone: int | None = None

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

@router.post("/update_account", response_model=SafeUser)
async def update_account(user: User = Depends(get_current_active_user), data: UserUpdatable = Depends(UserUpdatable), db: AsyncSession = Depends(get_db)):
        for k, v in data:
            if v is not None:
                setattr(user, k, v)
        
        await db.commit()
        await db.refresh(user)

        return user

@router.post("/activities", response_model=ActivityResponse)
async def create_activity(
    activity: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
    assigned_to: int | None = None
):
    if assigned_to is not None:
        if not user.is_coach:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only coaches can assign activities to clients."
            )

        query = select(CoachLink).where(
            and_(
                CoachLink.client_id == assigned_to,
                CoachLink.coach_id == user.id
            )
        )
        result = await db.execute(query)
        client_link = result.scalars().first()

        if not client_link:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot assign activity to a user who is not your client."
            )

        new_activity = Activity(
            name=activity.name,
            description=activity.description,
            user_id=assigned_to,
            assigned_by_id=user.id,
            assigned_by_coach=True,
            activity_type=activity.activity_type,
            target_value=activity.target_value,
            progress_value=0,
            unit=activity.unit,
            due_at=activity.due_at,
            status=ActivityStatus.PENDING,
        )
    else:
        new_activity = Activity(
            name=activity.name,
            description=activity.description,
            user_id=user.id,
            assigned_by_id=user.id,
            assigned_by_coach=False,
            activity_type=activity.activity_type,
            target_value=activity.target_value,
            progress_value=0,
            unit=activity.unit,
            due_at=activity.due_at,
            status=ActivityStatus.PENDING,
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
    if not user.is_coach:
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
    # Non-coach users can only access their own data
    if not current_user.is_coach:
        if target_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Clients can only access their own data")
        return

    # Coaches can access their own data
    if target_user_id == current_user.id:
        return

    # Coaches can access linked clients
    link_stmt = select(CoachLink).where(
        CoachLink.coach_id == current_user.id,
        CoachLink.client_id == target_user_id,
    )
    link = (await db.execute(link_stmt)).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="Not your client")


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