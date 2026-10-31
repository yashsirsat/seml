# Razorpay booking payments

## Configure test mode

1. Create a Razorpay account and enable **Test Mode** in the Razorpay dashboard.
2. Create test API keys under **Account & Settings > API Keys**.
3. Add both keys to the project-root `.env` file:

   ```env
   RAZORPAY_KEY_ID=rzp_test_your_key_id
   RAZORPAY_KEY_SECRET=your_test_key_secret
   ```

4. Install dependencies and start the app:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe app.py
   ```

5. Sign in, select a service and seats, and use **Continue to secure payment**.
   The app creates a server-side Razorpay order, opens Checkout, verifies the
   callback signature, checks the payment against Razorpay, captures an
   authorized payment, and only then confirms the seats.

The project uses `FARE_PER_SEAT` as its fare source. Set a real fare before
accepting real payments; the example value is intentionally just `1`.

## Email confirmations

Gmail OAuth setup is documented in [GMAIL_SETUP.md](./GMAIL_SETUP.md). Once
authorized, successful bookings send a confirmation to the signed-in passenger.
Email setup is optional; a Gmail outage does not undo a paid booking, and the
application logs the email error.

## Deployment and safety

- Never put API keys in source code, templates, GitHub, screenshots, or chat.
- Keep `.env`, `credentials.json`, and `token.json` private. Do not copy the
  local `.env` file into a hosted deployment; configure secrets in the host's
  environment-variable settings.
- Use HTTPS for hosted deployments and set `HTTPS_ONLY=true`.
- Keep Razorpay in Test Mode until checkout, payment verification, seat
  contention, and email behavior have been tested end-to-end.
- To accept real payments, generate **Live Mode** keys and configure them only
  in the production host's secret manager. Verify the merchant account and
  comply with Razorpay's current onboarding and payment requirements.
- If Razorpay captures a payment but a seat is claimed concurrently, the app
  does not confirm the booking and displays a support/refund warning. Check the
  Razorpay dashboard and refund that payment.
- If no Razorpay keys are configured, the app exposes an explicitly labeled
  demo booking flow that does not charge money. If only one key is configured,
  checkout is blocked rather than silently falling back to demo mode.

This integration depends on the merchant's Razorpay account, payment settings,
network access, and valid credentials. It cannot be activated with placeholder
keys.
