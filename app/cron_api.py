# app/cron_api.py

from fastapi import APIRouter, Header, HTTPException, Depends
from app.database import get_db
from app.email_service import send_reminder_email
from supabase import Client
from datetime import date
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cron", tags=["cron"])

CRON_SECRET = os.getenv("CRON_SECRET", "change-this")
REMINDER_DAYS = {14, 7, 3, 1}


def _require_cron_secret(x_cron_secret: Optional[str] = Header(None)):
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")


def _days_until_next(date_str: str, today: date) -> Optional[int]:
    try:
        d = date.fromisoformat(str(date_str)[:10])
        next_occ = date(today.year, d.month, d.day)
        if next_occ < today:
            next_occ = date(today.year + 1, d.month, d.day)
        return (next_occ - today).days
    except Exception:
        return None


@router.post("/send-reminders")
async def send_reminders(
    _: None = Depends(_require_cron_secret),
    db: Client = Depends(get_db),
):
    today = date.today()
    sent_count = 0

    try:
        profiles_resp = db.table("user_profiles").select("*").execute()
        profiles = profiles_resp.data or []
    except Exception as e:
        logger.error("Failed to fetch user profiles: %s" % str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch profiles")

    for profile in profiles:
        user_email = profile.get("email")
        if not user_email:
            continue

        recipients = profile.get("saved_recipients") or []

        for recipient in recipients:
            if not recipient.get("reminder_enabled", True):
                continue

            recipient_id = recipient.get("id", "")
            partner_name = recipient.get("name", "Unknown")
            saved_gifts = recipient.get("saved_gifts") or []
            past_gift_names = [
                g.get("display_name") or g.get("name", "")
                for g in saved_gifts[:3]
                if g.get("display_name") or g.get("name")
            ]

            checks = [
                ("birthday", recipient.get("birthday"), None),
                ("anniversary", recipient.get("anniversary"), None),
                (
                    "custom",
                    recipient.get("custom_occasion_date"),
                    recipient.get("custom_occasion_name"),
                ),
            ]

            for occasion_key, date_str, custom_name in checks:
                if not date_str:
                    continue
                days = _days_until_next(date_str, today)
                if days is None or days not in REMINDER_DAYS:
                    continue
                try:
                    ok = send_reminder_email(
                        to=user_email,
                        partner_name=partner_name,
                        occasion=occasion_key,
                        days_until=days,
                        partner_id=recipient_id,
                        past_gifts=past_gift_names,
                        custom_occasion_name=custom_name,
                    )
                    if ok:
                        sent_count += 1
                        logger.info(
                            "Sent %s reminder for %s to %s (%d days out)"
                            % (occasion_key, partner_name, user_email, days)
                        )
                    else:
                        logger.error(
                            "Reminder send failed for %s/%s to %s"
                            % (partner_name, occasion_key, user_email)
                        )
                except Exception as e:
                    logger.error(
                        "Error sending reminder for %s/%s: %s"
                        % (partner_name, occasion_key, str(e))
                    )

    return {"sent": sent_count, "date": str(today)}


@router.post("/test-email")
async def test_email(
    body: Optional[dict] = None,
    _: None = Depends(_require_cron_secret),
):
    to = (body or {}).get("to") or os.getenv("TEST_EMAIL")
    if not to:
        raise HTTPException(
            status_code=400,
            detail="No recipient — provide 'to' in body or set TEST_EMAIL env var",
        )

    try:
        ok = send_reminder_email(
            to=to,
            partner_name="Sarah",
            occasion="birthday",
            days_until=7,
            partner_id="test-id",
            past_gifts=["Faux Fur Blanket", "Bath Bombs Set"],
        )
        return {
            "sent": ok,
            "message": "Test email sent successfully" if ok else "Failed to send test email",
        }
    except Exception as e:
        logger.error("test-email error: %s" % str(e))
        return {"sent": False, "message": str(e)}
