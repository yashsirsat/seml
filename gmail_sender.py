import base64
import os
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
PROJECT_DIR = Path(__file__).resolve().parent


class GmailNotConfigured(Exception):
    """Raised when Gmail OAuth has not been set up for this installation."""


def _oauth_path(env_name, default_name):
    path = Path(os.environ.get(env_name, default_name))
    return path if path.is_absolute() else PROJECT_DIR / path


def _load_credentials():
    token_path = _oauth_path("GOOGLE_OAUTH_TOKEN_FILE", "token.json")
    client_secrets_path = _oauth_path(
        "GOOGLE_OAUTH_CLIENT_SECRETS", "credentials.json"
    )

    if not token_path.is_file():
        raise GmailNotConfigured("Run setup_gmail.py to authorize Gmail.")

    credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials.valid:
        return credentials

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    if not client_secrets_path.is_file():
        raise GmailNotConfigured(
            "Gmail authorization expired; restore credentials.json and rerun setup_gmail.py."
        )
    raise GmailNotConfigured("Run setup_gmail.py to authorize Gmail again.")


def send_booking_confirmation(recipient, passenger_name, bus_key, seat_numbers, fare):
    credentials = _load_credentials()
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    message = MIMEText(
        f"Hi {passenger_name}, your MSRTC booking is confirmed.\n"
        f"Bus: {bus_key}\n"
        f"Seats: {', '.join(str(seat) for seat in seat_numbers)}\n"
        f"Total fare: Rs. {fare}\n"
        "Thank you for travelling with MSRTC."
    )
    message["To"] = recipient
    message["From"] = "me"
    message["Subject"] = "MSRTC booking confirmation"

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw_message})
        .execute()
    )
