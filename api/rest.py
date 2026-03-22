from fastapi import APIRouter, Depends, HTTPException, status, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import selectinload
from sqlalchemy import or_
from models import Notification

import asyncio
import json

from pydantic import BaseModel, ConfigDict

from db import get_db
from models import Item, User, CoachLink, Activity, Biometric, BiometricType, ActivityStatus, ActivityType, CoachInvites
from api.auth import get_current_active_user, Token

class SafeUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: str
    phone: int | None = None
    firstName: str
    lastName: str
    username: str
    is_coach: bool
    id: int


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
    is_coach: bool | None = None

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

active_streams={}

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

@router.post("/update_account", response_model="SafeUser")
async def update_account(
    data: UserUpdatable,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # 🔥 Check duplicates
    if data.email or data.phone:
        query = select(User).where(
            and_(
                User.id != user.id,
                or_(
                    User.email == data.email if data.email else False,
                    User.phone == data.phone if data.phone else False,
                )
            )
        )
        existing = (await db.execute(query)).scalars().first()

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Email or phone already in use",
            )

    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)

    return user


@router.get("/notifications/stream")
async def notification_stream(user: User = Depends(get_current_active_user)):
    async def event_publisher():
        queue = asyncio.Queue()

        active_streams.pop(user.id, None)
        active_streams[user.id] = queue

        try:
            while True:
                msg = await queue.get()
                yield f"data: {json.dumps(msg)}\n\n"
        finally:
            active_streams.pop(user.id, None)

    return StreamingResponse(event_publisher(), media_type="text/event-stream")


@router.post("/client-invite")
async def invite_client(
    client_id: int,
    coach: User = Depends(get_current_active_user),
):
    if client_id not in active_streams:
        return {
            "status": "offline",
            "message": "User is not online, invite not sent"
        }

    invite_payload = {
        "type": "coach_invite",
        "coach_id": coach.id,
        "client_id": client_id,
        "message": f"Coach {coach.id} invited you"
    }

    try:
        await active_streams[client_id].put(invite_payload)
    except Exception:
        return {
            "status": "failed",
            "message": "Could not deliver invite"
        }

    return {
        "status": "sent",
        "message": "Invite delivered in real-time"
    }


@router.post("/coach/add-client")
async def add_client(
    client_id: int,
    coach: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # 1. Ensure user is a coach
    if not coach.is_coach:
        raise HTTPException(status_code=403, detail="Only coaches can add clients")

    # 2. Check if client exists
    client = await db.execute(
        select(User).where(User.id == client_id)
    )
    client = client.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # 3. Check if already linked
    existing = await db.execute(
        select(CoachLink).where(
            CoachLink.coach_id == coach.id,
            CoachLink.client_id == client_id
        )
    )
    existing = existing.scalar_one_or_none()

    if existing:
        return {"status": "already_exists", "message": "Client already added"}

    # 4. Create link
    link = CoachLink(
        coach_id=coach.id,
        client_id=client_id
    )

    db.add(link)
    await db.commit()

    return {
        "status": "success",
        "message": "Client added successfully"
    }

@router.delete("/coach/remove-client")
async def remove_client(
    client_id: int,
    coach: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not coach.is_coach:
        raise HTTPException(status_code=403, detail="Only coaches allowed")

    stmt = delete(CoachLink).where(
        CoachLink.coach_id == coach.id,
        CoachLink.client_id == client_id
    )

    result = await db.execute(stmt)

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Client not found")

    await db.commit()

    return {"status": "client removed"}

@router.post("/accept-invite")
async def accept_invite(coach: int, client: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)):

    query = select(CoachInvites).where(
        and_(CoachInvites.coach_id == coach, 
            CoachInvites.client_id == client.id)
        )
    res = await db.execute(query)
    valid_invite = False
    for instance in res.scalars().all():
        if instance.expires > datetime.now(timezone.utc):
            entry = CoachLink(
            client_id = instance.client_id,
            coach_id = instance.coach_id
            )
            db.add(entry)
            valid_invite = True
            break
    
    if valid_invite:
        delete_query = delete(CoachInvites).where(
            CoachInvites.coach_id == coach,
            CoachInvites.client_id == client.id
        )
        await db.execute(delete_query)
        await db.commit()
        return {"status": "coach added successfully"}


    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no valid invites or invites expired")

@router.get("/notifications/history")
async def get_notifications(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
    )

    return res.scalars().all()

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