import os
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_sender import PROJECT_DIR, SCOPES, _oauth_path


def main():
    load_dotenv(PROJECT_DIR / ".env")
    client_secrets_path = _oauth_path(
        "GOOGLE_OAUTH_CLIENT_SECRETS", "credentials.json"
    )
    token_path = _oauth_path("GOOGLE_OAUTH_TOKEN_FILE", "token.json")

    if not client_secrets_path.is_file():
        raise SystemExit(
            "credentials.json is missing. Download an OAuth Desktop app client "
            "from Google Cloud Console and place it in the project folder."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets_path), SCOPES
    )
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    print("Gmail authorization saved locally. Keep credentials.json and token.json private.")


if __name__ == "__main__":
    main()
