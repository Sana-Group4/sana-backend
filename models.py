from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String,Integer,DateTime,ForeignKey,Enum,Float,Index
import enum
from db import Base
from datetime import datetime

class BiometricType(enum.Enum):
    HEART_RATE_BPM = "heart_rate_bpm"
    WORKOUT_SESSION = "workout_session"
    WEIGHT_KG = "weight_kg"
    STEPS_PER_DAY = "steps_per_day"
    CALORIES_BURNED_PER_DAY = "calories_per_day"

class UserType(enum.Enum):
    CLIENT = "Client"
    COACH = "Coach"

class AuthProvider(enum.Enum):
    LOCAL = "Local"
    GOOGLE = "Google"

class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    firstName: Mapped[str] = mapped_column(String(50), unique=False, nullable=False)
    lastName: Mapped[str] = mapped_column(String(50), unique=False, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=True)
    phone: Mapped[int] = mapped_column(Integer(), unique = True, nullable = True)
    hashedPass: Mapped[str] = mapped_column(String(255), unique=False, nullable=True)
    userType: Mapped[UserType] = mapped_column(Enum(UserType, values_callable=lambda x: [e.value for e in x]), unique = False, nullable=False)

    authProvider: Mapped[AuthProvider] = mapped_column(Enum(AuthProvider, values_callable=lambda x: [e.value for e in x]), unique=False, nullable= False)
    google_id: Mapped[str] = mapped_column(String(20), unique=False, nullable=True)

    #deletes databse entries when user removed
    refresh_tokens = relationship("RefreshTokens", back_populates="user", cascade="all, delete-orphan")
    activities = relationship("Activity", back_populates="user", cascade="all, delete-orphan")
    preference: Mapped["Preference"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    biometrics: Mapped[list["Biometric"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    coach_links: Mapped[list["CoachLink"]] = relationship("CoachLink", foreign_keys="CoachLink.coach_id", back_populates="coach", cascade="all, delete-orphan")
    client_links: Mapped[list["CoachLink"]] = relationship("CoachLink", foreign_keys="CoachLink.client_id", back_populates="client", cascade="all, delete-orphan")
    clients: Mapped[list["User"]] = relationship( "User", secondary="coaches", primaryjoin="User.id == CoachLink.coach_id", secondaryjoin="User.id == CoachLink.client_id", viewonly=True)
    coaches: Mapped[list["User"]] = relationship("User", secondary="coaches", primaryjoin="User.id == CoachLink.client_id", secondaryjoin="User.id == CoachLink.coach_id", viewonly=True)

class Preference(Base):
    __tablename__ = "preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preference_info: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    user: Mapped["User"] = relationship(back_populates="preference")

class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    user: Mapped["User"] = relationship(back_populates="activities")

class CoachLink(Base):
    __tablename__ = "coaches"
    
    coach_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    coach: Mapped["User"] = relationship("User", foreign_keys=[coach_id], back_populates="coach_links")
    client: Mapped["User"] = relationship("User", foreign_keys=[client_id], back_populates="client_links")

class Biometric(Base):
    __tablename__ = "biometrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    biometric_type: Mapped[BiometricType] = mapped_column( Enum(BiometricType, values_callable=lambda x: [e.value for e in x]), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    value_float: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_int: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped["User"] = relationship(back_populates="biometrics")


class RefreshTokens(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token: Mapped[str] = mapped_column(String(255))
    expireTime: Mapped[datetime] = mapped_column(DateTime(), nullable=False)

    #allows for 'instance.user' to get user entry
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")