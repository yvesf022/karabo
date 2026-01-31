import os
import logging
import requests

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Karabo Online Store")
EMAIL_FROM_ADDRESS = os.getenv(
    "EMAIL_FROM_ADDRESS",
    f"postmaster@{MAILGUN_DOMAIN}" if MAILGUN_DOMAIN else None,
)

logger = logging.getLogger(__name__)


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str | None = None,
) -> bool:
    """
    Send email via Mailgun HTTP API.

    HARD GUARANTEES:
    - NEVER raises exceptions
    - NEVER crashes app or request
    - Returns True on success, False on failure
    """

    # Absolute safety check (do NOT crash app)
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN or not EMAIL_FROM_ADDRESS:
        logger.error(
            "Mailgun not configured | domain=%s from=%s",
            MAILGUN_DOMAIN,
            EMAIL_FROM_ADDRESS,
        )
        return False

    data = {
        "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>",
        "to": to_email,
        "subject": subject,
        "html": html_content,
    }

    if text_content:
        data["text"] = text_content

    try:
        response = requests.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data=data,
            timeout=10,
        )

        if response.status_code != 200:
            logger.error(
                "Mailgun email failed | to=%s | status=%s | response=%s",
                to_email,
                response.status_code,
                response.text,
            )
            return False

        return True

    except Exception as e:
        # FINAL SAFETY NET — email can NEVER break business logic
        logger.exception(
            "Mailgun email exception | to=%s | error=%s",
            to_email,
            str(e),
        )
        return False
