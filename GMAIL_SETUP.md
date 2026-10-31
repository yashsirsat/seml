# Gmail booking confirmations

1. In Google Cloud Console, enable the Gmail API and create an OAuth client ID for a **Desktop app**.
2. Download its client-secret JSON and save it as `credentials.json` in the project folder. Do not commit or share it.
3. Run `.\.venv\Scripts\python.exe setup_gmail.py` from the project folder and sign in to the sender account in the browser.
4. The flow saves `token.json` locally. Both OAuth files are ignored by Git.
5. Restart the Flask app. Booking confirmations will then be sent to the passenger's account email using Gmail API.

The first authorization requires internet access and a browser. If Google marks the OAuth app as unverified, use a Google account added as a test user in the OAuth consent screen. Never paste account passwords, client secrets, or token contents into chat.
