import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# =====================================================
# EMAIL CONFIG (GMAIL SMTP)
# =====================================================

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Karabo Online Store")

if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
    raise RuntimeError("GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set")


# =====================================================
# CORE EMAIL SENDER
# =====================================================

def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str | None = None,
):
    """
    Send an email using Gmail SMTP (SSL).
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{EMAIL_FROM_NAME} <{GMAIL_ADDRESS}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    if text_content:
        msg.attach(MIMEText(text_content, "plain"))

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(
                GMAIL_ADDRESS,
                to_email,
                msg.as_string(),
            )
    except Exception as e:
        # Do NOT leak internal error details
        raise RuntimeError("Failed to send email") from e
