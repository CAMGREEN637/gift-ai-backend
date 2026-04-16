import resend
import os
from typing import Optional
from datetime import date

resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "reminders@yourdomain.com")
APP_URL = os.getenv("NEXT_PUBLIC_APP_URL", "https://yourdomain.com")


def _reminder_html(
    partner_name: str,
    occasion: str,
    days_until: int,
    partner_id: str,
    past_gifts: list[str],
) -> str:
    occasion_emoji = {
        "birthday": "🎂",
        "anniversary": "💝",
    }.get(occasion, "🎁")

    timing = "tomorrow" if days_until == 1 else f"in {days_until} days"
    gift_link = f"{APP_URL}/?partner_id={partner_id}"

    past_section = ""
    if past_gifts:
        items = "".join(f"<li>{g}</li>" for g in past_gifts[:3])
        past_section = f"""
        <p style="color:#78716c;font-size:14px;margin-top:20px;">
          <strong>Gifts she's liked before:</strong>
        </p>
        <ul style="color:#78716c;font-size:14px;">{items}</ul>
        """

    return f"""
    <div style="font-family:'Georgia',serif;max-width:520px;margin:0 auto;padding:40px 20px;background:#fffdf9;">
      <h1 style="font-size:28px;color:#1c1917;margin-bottom:8px;">
        {occasion_emoji} {partner_name}'s {occasion} is {timing}
      </h1>
      <p style="color:#78716c;font-size:16px;line-height:1.6;">
        Don't leave it to the last minute — we'll help you find something she'll genuinely love.
      </p>
      {past_section}
      <a href="{gift_link}"
         style="display:inline-block;margin-top:24px;padding:14px 28px;
                background:#1c1917;color:white;text-decoration:none;
                border-radius:12px;font-size:15px;font-weight:600;">
        Find the perfect gift →
      </a>
      <p style="color:#a8a29e;font-size:12px;margin-top:40px;">
        You're receiving this because you saved {partner_name}'s {occasion} in Gift AI.<br>
        <a href="{APP_URL}/account" style="color:#a8a29e;">Manage reminders</a>
      </p>
    </div>
    """


def send_reminder_email(
    to: str,
    partner_name: str,
    occasion: str,
    days_until: int,
    partner_id: str,
    past_gifts: list[str] = [],
) -> bool:
    subject_map = {
        "birthday":    f"🎂 {partner_name}'s birthday is {'tomorrow' if days_until == 1 else f'in {days_until} days'}",
        "anniversary": f"💝 Your anniversary with {partner_name} is {'tomorrow' if days_until == 1 else f'in {days_until} days'}",
    }
    subject = subject_map.get(occasion, f"🎁 {partner_name}'s {occasion} is coming up")

    try:
        resend.Emails.send({
            "from":    FROM_EMAIL,
            "to":      [to],
            "subject": subject,
            "html":    _reminder_html(partner_name, occasion, days_until, partner_id, past_gifts),
        })
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to send reminder to {to}: {e}")
        return False