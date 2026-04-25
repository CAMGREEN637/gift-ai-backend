# app/email_service.py

import resend
import os
import logging

logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "reminders@giftd.ai")
APP_URL = os.getenv("NEXT_PUBLIC_APP_URL", "https://giftd.ai")


def _build_subject(
    partner_name: str,
    occasion: str,
    days_until: int,
    custom_occasion_name: str = None,
) -> str:
    timing = "tomorrow" if days_until == 1 else f"in {days_until} days"
    if occasion == "birthday":
        return f"🎂 {partner_name}'s birthday is {timing}"
    elif occasion == "anniversary":
        return f"💝 Your anniversary with {partner_name} is {timing}"
    else:
        label = custom_occasion_name or occasion.replace("_", " ").title()
        return f"🎁 {label} for {partner_name} is {timing}"


def _build_html(
    partner_name: str,
    occasion: str,
    days_until: int,
    partner_id: str,
    past_gifts: list,
    custom_occasion_name: str = None,
) -> str:
    timing = "tomorrow" if days_until == 1 else f"in {days_until} days"
    first_name = partner_name.split()[0]

    if occasion == "birthday":
        icon = "🎂"
        headline = f"{icon} {partner_name}'s birthday is {timing}"
        cta_text = "Find the perfect birthday gift →"
        footer_occasion = "birthday"
    elif occasion == "anniversary":
        icon = "💝"
        headline = f"{icon} Your anniversary with {partner_name} is {timing}"
        cta_text = "Find the perfect anniversary gift →"
        footer_occasion = "anniversary"
    else:
        icon = "🎁"
        label = custom_occasion_name or occasion.replace("_", " ").title()
        headline = f"{icon} {label} for {partner_name} is {timing}"
        cta_text = "Find the perfect gift →"
        footer_occasion = label

    gift_url = f"{APP_URL}/?partner_id={partner_id}"
    manage_url = f"{APP_URL}/partners"

    past_gifts_html = ""
    if past_gifts:
        gift_items = "".join(
            f'<li style="margin: 4px 0; color: #57534e; font-size: 14px; line-height: 1.5;">{g}</li>'
            for g in past_gifts[:3]
        )
        past_gifts_html = f"""
          <div style="margin-top: 28px; padding: 16px 20px; background-color: #f5f5f4; border-radius: 12px;">
            <p style="margin: 0 0 10px 0; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #a8a29e;">
              Gifts {first_name} has liked before
            </p>
            <ul style="margin: 0; padding-left: 18px;">
              {gift_items}
            </ul>
          </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{headline}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f2ede8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f2ede8; padding: 40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" width="520" style="max-width: 520px; width: 100%; background-color: #fffdf9; border-radius: 20px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.07);">

          <!-- Logo header -->
          <tr>
            <td style="padding: 28px 36px 24px; border-bottom: 1px solid #e7e5e4;">
              <p style="margin: 0; font-family: Georgia, 'Times New Roman', serif; font-size: 20px; color: #1c1917; letter-spacing: -0.02em;">
                Giftd
              </p>
            </td>
          </tr>

          <!-- Main body -->
          <tr>
            <td style="padding: 36px 36px 32px;">
              <p style="margin: 0 0 16px 0; font-family: Georgia, 'Times New Roman', serif; font-size: 26px; font-weight: 400; color: #1c1917; line-height: 1.3;">
                {headline}
              </p>
              <p style="margin: 0 0 28px 0; font-size: 15px; color: #78716c; line-height: 1.65;">
                Don't leave it too late — we've picked some ideas {first_name} will actually love.
              </p>

              <!-- CTA button -->
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background-color: #1c1917; border-radius: 12px;">
                    <a href="{gift_url}"
                       style="display: inline-block; padding: 14px 28px; font-size: 15px; font-weight: 600; color: #ffffff; text-decoration: none; letter-spacing: -0.01em;">
                      {cta_text}
                    </a>
                  </td>
                </tr>
              </table>

              {past_gifts_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 20px 36px 28px; border-top: 1px solid #e7e5e4;">
              <p style="margin: 0; font-size: 12px; color: #a8a29e; line-height: 1.7;">
                You're receiving this because you saved {partner_name}'s {footer_occasion} in Giftd.
                <br />
                <a href="{manage_url}" style="color: #a8a29e; text-decoration: underline;">Manage reminders</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_reminder_email(
    to: str,
    partner_name: str,
    occasion: str,
    days_until: int,
    partner_id: str,
    past_gifts: list = None,
    custom_occasion_name: str = None,
) -> bool:
    if past_gifts is None:
        past_gifts = []
    try:
        subject = _build_subject(partner_name, occasion, days_until, custom_occasion_name)
        html = _build_html(partner_name, occasion, days_until, partner_id, past_gifts, custom_occasion_name)
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        logger.info(
            "Reminder sent to %s for %s's %s (%d days out)"
            % (to, partner_name, occasion, days_until)
        )
        return True
    except Exception as e:
        logger.error("Failed to send reminder email to %s: %s" % (to, str(e)))
        return False
