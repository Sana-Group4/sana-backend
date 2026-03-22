from fastapi import APIRouter, Depends, HTTPException, status, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete, or_
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import selectinload

import asyncio

from pydantic import BaseModel, ConfigDict

from db import get_db
from models import Item, User, CoachLink, Activity, Biometric, BiometricType, ActivityStatus, ActivityType, CoachInvites, Session, CoachInfo, CoachMessages
from api.auth import get_current_active_user, Token

class SafeUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email: str
    phone: int | None = None
    firstName: str
    lastName: str
    username: str
    id: int
    is_coach: bool

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

class SessionInfo(BaseModel):
    client_id: int
    title: str
    desc: str
    date_time: datetime
    duration: int = 0


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

class Message(BaseModel):
    content: str
    receiver_id: int

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

@router.post("/update_account", response_model=SafeUser)
async def update_account(user: User = Depends(get_current_active_user), data: UserUpdatable = Depends(UserUpdatable), db: AsyncSession = Depends(get_db)):
        for k, v in data:
            if v is not None:
                setattr(user, k, v)
        
        await db.commit()
        await db.refresh(user)

        return user

@router.get("/notifications")
async def notification_stream(user: User = Depends(get_current_active_user)):
    async def event_publisher():

        queue = asyncio.Queue()
        active_streams[user.id] = queue

        try:
            while True:
                msg  = await queue.get()
                yield f"data: {msg}\n\n"
        except asyncio.CancelledError:
            active_streams.pop(user.id, None)
    
    return StreamingResponse(event_publisher(), media_type="text/event-stream")

@router.post("/book-session")
async def book_session(session_info:SessionInfo = Depends(SessionInfo), coach: User = Depends(get_current_active_user),db: AsyncSession = Depends(get_db)):
    session = Session(
        client_id = session_info.client_id,
        coach_id = coach.id,
        date_time = session_info.date_time,
        session_title = session_info.title,
        session_desc = session_info.desc,
        session_duration = session_info.duration
    )

    if session.session_duration:
        query = select(Session).where(and_(
            Session.date_time >= session.date_time.astimezone(tz=timezone.utc), Session.date_time <= session.date_time.astimezone(tz=timezone.utc)+timedelta(minutes=session.session_duration)
        ))
    
    res = await db.execute(query)
    entry = res.scalars().first()

    if entry:
        return {"status": "session already booked in given time slot"}

    db.add(session)
    await db.commit()
    return {"status": "session added successfully"}

@router.get("/coach-info")
async def get_coach_info(coach_id: int|None = None, user: User = Depends(get_current_active_user),db: AsyncSession = Depends(get_db)):
    to_get = None
    if coach_id == None:
        to_get = user.id
    else:
        to_get = coach_id

        auth_query = select(CoachLink).where(
            and_(CoachLink.coach_id == to_get, CoachLink.client_id == user.id)
        )
        res = await db.execute(auth_query)
        entry = res.scalars().first()
        if not entry:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no link found with provided coach")
    
    query = select(CoachInfo).where(CoachInfo.coach_id == to_get)

    res = await db.execute(query)

    entry = res.scalars().first()

    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error: no coach info found")

    return entry

@router.get("/client-get-sessions")
async def client_get_sessions(coach_id: int, user: User = Depends(get_current_active_user),db: AsyncSession = Depends(get_db)):
    query = select(Session).where(
        and_(Session.coach_id == coach_id, Session.client_id == user.id)
        )
    
    res = await db.execute(query)
    entry = res.scalars().all()

    if not entry:
        return {"status": "No bookings registered for this coach"}
    
    return entry

@router.post("/send_message")
async def send_message(message:Message, user:User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)):
    user1_id = min(message.receiver_id, user.id)
    user2_id = max(message.receiver_id, user.id)
    new_message = CoachMessages(
        user_1 = user1_id,
        user_2 = user2_id,
        time_sent = datetime.now(timezone.utc),
        content = message.content
    )
    db.add(new_message)
    await db.commit()

    #need to add notifications

    return {"status": "success"}

@router.get("/get_messages")
async def send_message(other_id: int , user:User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)):
    userid_1 = min(other_id, user.id)
    userid_2 = max(other_id, user.id)

    query = select(CoachMessages).where(and_(
        CoachMessages.user_1 == userid_1, CoachMessages.user_2 == userid_2
    ))

    res = await db.execute(query)

    entries = res.scalars().all()

    if not entries:
        return {"status": "no messages"}
    
    return entries


@router.get("/coach-get-sessions")
async def coach_get_sessions(client_id: int, user: User = Depends(get_current_active_user),db: AsyncSession = Depends(get_db)):
    query = select(Session).where(
        and_(Session.coach_id == user.id, Session.client_id == client_id)
        )
    
    res = await db.execute(query)
    entry = res.scalars().all()

    if not entry:
        return {"status": "No bookings registered for this client"}
    
    return entry

@router.post("/remove-client")
async def remove_client(client_id: int, coach: User = Depends(get_current_active_user) ,db: AsyncSession = Depends(get_db)):
    if not coach.is_coach:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="this feature is only available to coaches")

    query = delete(CoachLink).where(and_(
        CoachLink.client_id == client_id,
        CoachLink.coach_id == coach.id
    ))

    res = await db.execute(query)

    if res:
        await db.commit()
        return {"status": "removed client successfully"}
    
    return {"status": "No client link found"}    

@router.post("/client-invite")
async def invite_client(client_id:int ,coach: User = Depends(get_current_active_user) ,db: AsyncSession = Depends(get_db)):
    if not coach.is_coach:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="this feature is only available to coaches")

    invite = CoachInvites(
        client_id = client_id,
        coach_id = coach.id,
        expires = datetime.now(timezone.utc) + timedelta(days = 10)
    )

    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    if client_id in active_streams:
        await active_streams[client_id].put(f"Coach {coach.id} sent you an invite!")
        return {"status": "Client notified"}
    
    return {"status": "Invite saved, but client is offline (they'll see it next login)"}

@router.get("/get-coach-invites")
async def get_coach_invites(user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)):
    query = select(CoachInvites). where(
        CoachInvites.client_id == user.id
    )
    res = await db.execute(query)
    entries = res.scalars().all()
    return entries

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