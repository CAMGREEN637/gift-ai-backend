from fastapi import APIRouter, Header, HTTPException, Depends
from supabase import Client
from app.database import get_db
from app.email_service import send_reminder_email
from datetime import date
import os

cron_router = APIRouter(prefix="/cron", tags=["cron"])
CRON_SECRET = os.getenv("CRON_SECRET", "40ce557ed67cb1895db0a1022f1668740624d498635f821847d82fc4d7fcc9a6")


@cron_router.post("/send-reminders")
async def send_reminders(
    x_cron_secret: str = Header(None),
    db: Client = Depends(get_db),
):
    # Simple secret header so random people can't trigger mass emails
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401)

    today = date.today()
    reminders_sent = 0

    # Pull all user profiles that have recipients with dates set
    profiles = db.table("user_profiles").select("*").execute().data or []

    for profile in profiles:
        user_email = profile.get("email")
        if not user_email:
            continue

        for recipient in profile.get("saved_recipients", []):
            partner_id   = recipient.get("id")
            partner_name = recipient.get("name", "")
            past_gifts   = [
                g.get("display_name") or g.get("name", "")
                for g in recipient.get("saved_gifts", [])
            ]

            for occasion, field in [("birthday", "birthday"), ("anniversary", "anniversary")]:
                raw_date = recipient.get(field)
                if not raw_date:
                    continue

                try:
                    occasion_date = date.fromisoformat(str(raw_date)[:10])
                except ValueError:
                    continue

                # Next occurrence this year or next
                next_occurrence = occasion_date.replace(year=today.year)
                if next_occurrence < today:
                    next_occurrence = next_occurrence.replace(year=today.year + 1)

                days_until = (next_occurrence - today).days

                # Send at 14 days and 7 days out
                if days_until in (14, 7, 3, 1):
                    sent = send_reminder_email(
                        to=user_email,
                        partner_name=partner_name,
                        occasion=occasion,
                        days_until=days_until,
                        partner_id=partner_id,
                        past_gifts=past_gifts,
                    )
                    if sent:
                        reminders_sent += 1

    return {"sent": reminders_sent, "date": str(today)}