#database.py
from sqlalchemy import create_engine, Column, String, Boolean, Integer, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

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


def init_db():
    Base.metadata.create_all(bind=engine)
