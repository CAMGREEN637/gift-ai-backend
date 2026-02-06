#database.py
from sqlalchemy import create_engine, Column, String, Boolean, Integer, JSON, DateTime, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./giftai.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(String, primary_key=True)
    interests = Column(JSON)
    vibe = Column(JSON)


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    gift_name = Column(String)
    liked = Column(Boolean)


class InferredPreference(Base):
    __tablename__ = "inferred_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    category = Column(String)  # "interest" or "vibe"
    value = Column(String)
    weight = Column(Integer)


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String, index=True, nullable=False)
    tokens_used = Column(Integer, nullable=False)
    model_name = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)

    __table_args__ = (
        Index('idx_ip_timestamp', 'ip_address', 'timestamp'),
    )


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    """
    Dependency for FastAPI to get database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
