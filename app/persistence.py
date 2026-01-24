#persistence.py
from app.database import SessionLocal, UserPreference, Feedback, InferredPreference

# ---------- Preferences ----------

def save_preferences(user_id, interests, vibe):
    db = SessionLocal()
    existing = db.query(UserPreference).filter_by(user_id=user_id).first()

    if existing:
        existing.interests = interests
        existing.vibe = vibe
    else:
        db.add(UserPreference(
            user_id=user_id,
            interests=interests,
            vibe=vibe
        ))

    db.commit()
    db.close()


def get_preferences(user_id):
    db = SessionLocal()
    pref = db.query(UserPreference).filter_by(user_id=user_id).first()
    db.close()

    if not pref:
        return None

    return {
        "interests": pref.interests,
        "vibe": pref.vibe
    }


# ---------- Feedback ----------

def save_feedback(user_id, gift_name, liked):
    db = SessionLocal()
    db.add(Feedback(
        user_id=user_id,
        gift_name=gift_name,
        liked=liked
    ))
    db.commit()
    db.close()


def get_feedback(user_id):
    db = SessionLocal()
    rows = db.query(Feedback).filter_by(user_id=user_id).all()
    db.close()

    return [{"gift_name": r.gift_name, "liked": r.liked} for r in rows]


# ---------- Inferred Preferences ----------

def update_inferred(user_id, category, value):
    db = SessionLocal()
    row = db.query(InferredPreference).filter_by(
        user_id=user_id,
        category=category,
        value=value
    ).first()

    if row:
        row.weight += 1
    else:
        db.add(InferredPreference(
            user_id=user_id,
            category=category,
            value=value,
            weight=1
        ))

    db.commit()
    db.close()


def get_inferred(user_id):
    db = SessionLocal()
    rows = db.query(InferredPreference).filter_by(user_id=user_id).all()
    db.close()

    interests = {}
    vibe = {}

    for r in rows:
        if r.category == "interest":
            interests[r.value] = r.weight
        else:
            vibe[r.value] = r.weight

    return {"interests": interests, "vibe": vibe}