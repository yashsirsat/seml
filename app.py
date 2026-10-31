import csv
import hashlib
import hmac
import re
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from gmail_sender import GmailNotConfigured, send_booking_confirmation
import razorpay
import reverse_geocoder as rg
from datetime import datetime
import os
from math import isfinite
from pathlib import Path
from secrets import token_hex
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


load_dotenv()

app = Flask(__name__)
BUS_DATA_FILE = Path(__file__).resolve().parent / "msrtc_bus_data_sample.csv"
instance_dir = Path(app.instance_path)
instance_dir.mkdir(parents=True, exist_ok=True)
secret_key_path = instance_dir / "secret_key"
if os.environ.get("SECRET_KEY"):
    app.secret_key = os.environ["SECRET_KEY"]
else:
    if not secret_key_path.exists():
        secret_key_path.write_text(token_hex(32), encoding="utf-8")
    app.secret_key = secret_key_path.read_text(encoding="utf-8").strip()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
https_only = os.environ.get("HTTPS_ONLY")
app.config["SESSION_COOKIE_SECURE"] = (
    https_only.lower() in {"1", "true", "yes"}
    if https_only is not None
    else bool(os.environ.get("VERCEL"))
)
app.config["FARE_PER_SEAT"] = int(os.environ.get("FARE_PER_SEAT", "1"))
if app.config["FARE_PER_SEAT"] < 1:
    raise ValueError("FARE_PER_SEAT must be at least 1.")
app.config["RAZORPAY_KEY_ID"] = os.environ.get("RAZORPAY_KEY_ID", "")
app.config["RAZORPAY_KEY_SECRET"] = os.environ.get("RAZORPAY_KEY_SECRET", "")

# Database configuration - Vercel/Neon aware
# Fetch the Vercel/Neon database URL
db_url = os.environ.get("DATABASE_URL")

# SQLAlchemy requires the URL to start with 'postgresql://' but Neon provides 'postgres://'
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Use the cloud database if found on Vercel, otherwise fallback to local SQLite for your computer
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///local_fallback.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------- DATABASE MODELS -----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)

class BookingSeat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bus_key = db.Column(db.String(255), nullable=False)
    seat_number = db.Column(db.Integer, nullable=False)
    passenger_email = db.Column(db.String(120), nullable=False)
    booked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("bus_key", "seat_number", name="uq_booking_seat_service"),
    )

class BusLocation(db.Model):
    bus_key = db.Column(db.String(255), primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    location_name = db.Column(db.String(500), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    active = db.Column(db.Boolean, nullable=False, default=True)

# Initialize Database
with app.app_context():
    db.create_all()

# ----------------- HELPER FUNCTIONS -----------------

def get_unique_bus_data():
    bus_names = set()
    bus_types = set()
    bus_times = set()
    with open(BUS_DATA_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            bus_names.add(row['bus_name'])
            bus_types.add(row['bus_type'])
            bus_times.add(row['bus_start_time'])
    return sorted(bus_names), sorted(bus_types), sorted(bus_times)

def get_bus_services():
    with open(BUS_DATA_FILE, newline='', encoding='utf-8') as f:
        rows = csv.DictReader(f)
        services = {
            get_bus_key(row): row
            for row in rows
        }
    return sorted(services.values(), key=lambda row: (
        row['start_point'],
        row['end_point'],
        row['bus_name'],
        datetime.strptime(row['bus_start_time'], '%I:%M %p').time(),
    ))

def get_location_name(coords):
    lat, lon = coords
    
    # Try Nominatim (OpenStreetMap) for detailed street-level address
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&addressdetails=1"
        headers = {'User-Agent': 'MSRTCBusTracker/1.0'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            address = data.get('display_name', 'Unknown Location')
            return address
    except:
        pass  # Fallback to reverse_geocoder
    
    # Fallback to reverse_geocoder (offline)
    try:
        results = rg.search(coords)
        if results and len(results) > 0:
            place = results[0]
            return f"{place.get('name', 'Unknown')}, {place.get('admin2', 'N/A')}, {place.get('admin1', 'Unknown')}, India"
    except:
        pass
    
    return "Unknown Location"

def get_seat_map():
    return [
        [1, 2, None, None, None, 3, 4],
        [5, 6, None, None, None, 7, 8],
        [9, 10, None, None, None, 11, 12],
        [13, 14, None, None, None, 15, 16],
        [17, 18, None, None, None, 19, 20],
        [21, 22, None, None, None, 23, 24],
        [25, 26, None, None, None, 27, 28],
        [29, 30, None, None, None, 31, 32],
        [33, 34, None, None, None, 35, 36],
        [37, 38, 39, 40, 41, 42, 43],
    ]

def get_bus_key(bus):
    return f"{bus['bus_name']}|{bus['bus_type']}|{bus['bus_start_time']}"

def find_bus_service(bus_name, bus_type, bus_start_time):
    with open(BUS_DATA_FILE, newline='', encoding='utf-8') as f:
        return next(
            (
                row for row in csv.DictReader(f)
                if row['bus_name'] == bus_name
                and row['bus_type'] == bus_type
                and row['bus_start_time'] == bus_start_time
            ),
            None,
        )

def parse_coordinates(value):
    try:
        latitude, longitude = map(float, value.split(','))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Enter latitude and longitude separated by a comma.")
    if (not isfinite(latitude) or not isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError("Latitude or longitude is outside the valid range.")
    return latitude, longitude

def is_station_master():
    return session.get('user_role') == 'station_master'

def station_master_emails():
    return {
        email.strip().lower()
        for email in os.environ.get("STATION_MASTER_EMAILS", "").split(",")
        if email.strip()
    }

def read_location(bus_key):
    location = db.session.get(BusLocation, bus_key)
    if location is None:
        return None
    return (
        location.latitude,
        location.longitude,
        location.location_name,
        location.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        location.active,
    )


def create_razorpay_order(amount_in_rupees, booking_ref):
    if not razorpay_is_configured():
        raise RuntimeError("Razorpay keys are not configured.")
    client = razorpay_client()
    return client.order.create({
        "amount": amount_in_rupees * 100,
        "currency": "INR",
        "receipt": booking_ref,
        "notes": {"booking_ref": booking_ref},
    })


def razorpay_is_configured():
    return bool(app.config.get("RAZORPAY_KEY_ID") and app.config.get("RAZORPAY_KEY_SECRET"))


def razorpay_client():
    return razorpay.Client(auth=(
        app.config["RAZORPAY_KEY_ID"],
        app.config["RAZORPAY_KEY_SECRET"],
    ))


def verify_razorpay_signature(order_id, payment_id, signature, secret):
    body = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def save_location(bus_key, latitude, longitude, location_name):
    location = db.session.get(BusLocation, bus_key)
    if location is None:
        location = BusLocation(bus_key=bus_key)
        db.session.add(location)
    location.latitude = latitude
    location.longitude = longitude
    location.location_name = location_name
    location.updated_at = datetime.utcnow()
    location.active = True
    db.session.commit()


def tracking_bus_key(bus_name, bus_type, bus_start_time):
    return get_bus_key({
        "bus_name": bus_name,
        "bus_type": bus_type,
        "bus_start_time": bus_start_time,
    })


# ----------------- ROUTES -----------------

@app.route('/')
def index():
    return redirect(url_for('signin'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if (not name or len(name) > 100 or len(email) > 120
                or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)):
            flash('Enter a valid name and email address.')
            return render_template('signup.html')
        if len(password) < 8:
            flash('Password must be at least 8 characters.')
            return render_template('signup.html')
            
        # Check if user already exists in DB
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered.')
            return redirect(url_for('signin'))
            
        role = 'station_master' if email in station_master_emails() else 'user'
        new_user = User(name=name, email=email, password=password, role=role)
        new_user.password = generate_password_hash(password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Signup successful. Please signin.')
        return redirect(url_for('signin'))
    return render_template('signup.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        # Fetch user from DB
        user = User.query.filter_by(email=email).first()
        
        password_valid = False
        if user:
            if user.password.startswith(('scrypt:', 'pbkdf2:')):
                password_valid = check_password_hash(user.password, password)
            else:
                password_valid = user.password == password
                if password_valid:
                    user.password = generate_password_hash(password)
                    db.session.commit()
        if user and password_valid:
            session.clear()
            if user.email in station_master_emails() and user.role != 'station_master':
                user.role = 'station_master'
                db.session.commit()
            session['user_email'] = user.email
            session['user_name'] = user.name
            session['user_role'] = user.role
            return redirect(url_for('home'))
            
        flash('Invalid email or password.')
    return render_template('signin.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('signin'))

@app.route('/home')
def home():
    if 'user_email' not in session:
        return redirect(url_for('signin'))
    return render_template('home.html', name=session.get('user_name'), role=session.get('user_role'))

@app.route('/station_master', methods=['GET', 'POST'])
def station_master():
    if 'user_role' not in session or session['user_role'] != 'station_master':
        flash("Unauthorized access!")
        return redirect(url_for('signin'))
    bus_names, bus_types, bus_times = get_unique_bus_data()
    message = None
    if request.method == 'POST':
        try:
            bus_name = request.form['bus_name']
            bus_type = request.form['bus_type']
            bus_start_time = request.form['bus_start_time']
            if not find_bus_service(bus_name, bus_type, bus_start_time):
                raise ValueError("Choose a valid bus service.")
            lat, lon = parse_coordinates(request.form.get('location'))
            location_name = get_location_name((lat, lon))
            bus_key = tracking_bus_key(bus_name, bus_type, bus_start_time)
            save_location(bus_key, lat, lon, location_name)
            message = f"Bus '{bus_name}' ({bus_type}) at {bus_start_time} location updated to '{location_name}'."
        except (KeyError, ValueError) as error:
            flash(str(error))
    return render_template('station_master.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times, message=message)

@app.route('/api/auto_update_location', methods=['POST'])
def api_auto_update_location():
    if not is_station_master():
        return jsonify(success=False, message="Station master access required."), 403
    data = request.get_json(silent=True) or {}
    bus_name = data.get('bus_name')
    bus_type = data.get('bus_type')
    bus_start_time = data.get('bus_start_time')
    if not all((bus_name, bus_type, bus_start_time)):
        return jsonify(success=False, message="Bus name, type, and departure are required."), 400
    if not find_bus_service(bus_name, bus_type, bus_start_time):
        return jsonify(success=False, message="Choose a valid bus service."), 400
    try:
        lat = float(data.get('latitude'))
        lon = float(data.get('longitude'))
        lat, lon = parse_coordinates(f"{lat},{lon}")
    except (TypeError, ValueError):
        try:
            lat, lon = parse_coordinates(data.get('location'))
        except ValueError as error:
            return jsonify(success=False, message=str(error)), 400
    bus_key = tracking_bus_key(bus_name, bus_type, bus_start_time)
    save_location(bus_key, lat, lon, f"{lat:.5f}, {lon:.5f}")
    location = db.session.get(BusLocation, bus_key)
    return jsonify(
        success=True,
        message="GPS location updated.",
        timestamp=location.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )

@app.route('/bus_location_api')
def bus_location_api():
    bus_name = request.args.get('bus_name')
    bus_type = request.args.get('bus_type')
    bus_start_time = request.args.get('bus_start_time')
    if not all((bus_name, bus_type, bus_start_time)) or not find_bus_service(bus_name, bus_type, bus_start_time):
        return jsonify(available=False, message="Choose a valid bus service."), 400
    bus_key = tracking_bus_key(bus_name, bus_type, bus_start_time)
    loc_data = read_location(bus_key)
    if not loc_data:
        return jsonify(
            available=False,
            active=False,
            location="No location has been shared for this service yet.",
            timestamp=None,
            latitude=None,
            longitude=None,
        )
    return jsonify(
        available=True,
        active=loc_data[4],
        location=loc_data[2],
        timestamp=loc_data[3],
        latitude=loc_data[0],
        longitude=loc_data[1],
    )

@app.route('/api/get_started_buses')
def get_started_buses():
    with open(BUS_DATA_FILE, newline='', encoding='utf-8') as f:
        services = [
            {
                "bus_key": tracking_bus_key(row['bus_name'], row['bus_type'], row['bus_start_time']),
                "bus_name": row['bus_name'],
                "bus_type": row['bus_type'],
                "bus_start_time": row['bus_start_time'],
            }
            for row in csv.DictReader(f)
        ]
    active = [
        service for service in services
        if (
            (location := db.session.get(BusLocation, service["bus_key"]))
            and location.active
        )
    ]
    return jsonify(started_buses=[service["bus_key"] for service in active], active_buses=active)

@app.route('/api/stop_sharing/<bus_key>')
def api_stop_sharing_get(bus_key):
    return jsonify({"success": False, "message": "Use POST to stop sharing."}), 405

@app.route('/api/stop_sharing', methods=['POST'])
def api_stop_sharing():
    if not is_station_master():
        return jsonify(success=False, message="Station master access required."), 403
    data = request.get_json(silent=True) or {}
    bus_key = data.get('bus_key', '')
    location = db.session.get(BusLocation, bus_key)
    if not location or not location.active:
        return jsonify(success=False, message=f"{bus_key} not active"), 404
    location.active = False
    db.session.commit()
    return jsonify(success=True, message=f"Stopped sharing for {bus_key}")

@app.route('/payment', methods=['GET', 'POST'])
def payment():
    if 'user_email' not in session:
        flash("Please sign in to continue your booking.")
        return redirect(url_for('signin'))
    last_booking = session.get('last_booking')
    if not last_booking:
        return redirect(url_for('home'))
    seat_numbers = last_booking['seat_numbers']
    bus_key = last_booking['bus_key']
    valid_seats = {seat for row in get_seat_map() for seat in row if seat is not None}
    if (not isinstance(seat_numbers, list) or not seat_numbers
            or any(not isinstance(seat, int) or seat not in valid_seats for seat in seat_numbers)
            or len(set(seat_numbers)) != len(seat_numbers)):
        session.pop('last_booking', None)
        flash("Your pending booking is invalid. Please select your seats again.")
        return redirect(url_for('booking'))
    with open(BUS_DATA_FILE, newline='', encoding='utf-8') as f:
        valid_keys = {get_bus_key(row) for row in csv.DictReader(f)}
    if bus_key not in valid_keys:
        session.pop('last_booking', None)
        flash("That bus service is no longer available. Please choose another service.")
        return redirect(url_for('booking'))
    booked_seats = {
        booking.seat_number
        for booking in BookingSeat.query.filter_by(bus_key=bus_key).all()
    }
    is_payment_callback = request.method == 'POST' and any(
        request.form.get(field)
        for field in ('payment_id', 'order_id', 'signature')
    )
    if any(seat in booked_seats for seat in seat_numbers) and not is_payment_callback:
        session.pop('last_booking', None)
        flash("One or more selected seats are no longer available. Please choose again.")
        return redirect(url_for('booking'))
    fare = app.config["FARE_PER_SEAT"] * len(seat_numbers)
    has_razorpay_key = bool(
        app.config.get("RAZORPAY_KEY_ID") or app.config.get("RAZORPAY_KEY_SECRET")
    )
    razorpay_configured = razorpay_is_configured()

    def confirm_booking():
        user_email = session.get('user_email')
        user_name = session.get('user_name')
        try:
            db.session.add_all([
                BookingSeat(
                    bus_key=bus_key,
                    seat_number=seat_number,
                    passenger_email=user_email or "",
                )
                for seat_number in seat_numbers
            ])
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return False
        except Exception:
            db.session.rollback()
            raise

        if user_email:
            try:
                send_booking_confirmation(
                    recipient=user_email,
                    passenger_name=user_name,
                    bus_key=bus_key,
                    seat_numbers=seat_numbers,
                    fare=fare,
                )
                flash("Booking confirmed! Confirmation email sent successfully.")
            except GmailNotConfigured as error:
                app.logger.info("Booking email was not sent: %s", error)
                flash("Booking confirmed. Email is not connected yet; complete Gmail setup to enable notifications.")
            except Exception:
                app.logger.exception("Booking confirmation email failed")
                flash("Booking confirmed, but the confirmation email could not be sent.")
        else:
            flash("Booking confirmed, but no passenger email is available.")
        return True

    if request.method == 'POST':
        payment_id = request.form.get('payment_id', '').strip()
        callback_order_id = request.form.get('order_id', '').strip()
        signature = request.form.get('signature', '').strip()

        if payment_id or callback_order_id or signature:
            order_data = session.get('razorpay_order')
            if not razorpay_configured or not order_data:
                flash("Your Razorpay session expired. Please start checkout again.")
                return redirect(url_for('booking'))
            if (
                not payment_id
                or not callback_order_id
                or not signature
                or callback_order_id != order_data.get('id')
                or order_data.get('bus_key') != bus_key
                or order_data.get('seat_numbers') != seat_numbers
                or order_data.get('passenger_email') != session.get('user_email')
                or order_data.get('amount') != fare * 100
                or order_data.get('currency') != 'INR'
            ):
                flash("Payment details did not match this booking. Please retry checkout.")
                return redirect(url_for('payment'))
            if not verify_razorpay_signature(
                callback_order_id,
                payment_id,
                signature,
                app.config['RAZORPAY_KEY_SECRET'],
            ):
                flash("Payment signature verification failed. Please retry checkout.")
                return redirect(url_for('payment'))

            try:
                client = razorpay_client()
                payment = client.payment.fetch(payment_id)
                if (
                    payment.get('order_id') != order_data['id']
                    or payment.get('amount') != order_data['amount']
                    or payment.get('currency') != order_data['currency']
                ):
                    flash("Razorpay payment details did not match the order. The booking was not confirmed.")
                    return redirect(url_for('payment'))
                if payment.get('status') == 'authorized':
                    payment = client.payment.capture(
                        payment_id,
                        order_data['amount'],
                        {'currency': order_data['currency']},
                    )
                if payment.get('status') != 'captured':
                    flash("Payment has not been captured, so the booking was not confirmed.")
                    return redirect(url_for('payment'))
            except Exception:
                app.logger.exception("Razorpay payment verification or capture failed")
                flash("We could not verify the payment with Razorpay. The booking was not confirmed; contact support if your account was charged.")
                return redirect(url_for('payment'))

            if not confirm_booking():
                app.logger.error(
                    "Payment %s captured but seats became unavailable for bus %s",
                    payment_id,
                    bus_key,
                )
                flash("Payment was captured, but the seats were booked by someone else. Contact support for a refund.")
                return redirect(url_for('booking'))
            session.pop('razorpay_order', None)
            session.pop('last_booking', None)
            flash("Booking confirmed and payment captured successfully.")
            return redirect(url_for('home'))

        if request.form.get('payment_mode') == 'razorpay':
            if not razorpay_configured:
                flash("Razorpay is not fully configured. Add both Razorpay keys before starting checkout.")
                return render_template(
                    'payment.html',
                    seat_numbers=seat_numbers,
                    fare=fare,
                    razorpay_configured=False,
                    demo_mode=not has_razorpay_key,
                )
            current_order = session.get('razorpay_order')
            if (
                current_order
                and current_order.get('bus_key') == bus_key
                and current_order.get('seat_numbers') == seat_numbers
                and current_order.get('passenger_email') == session.get('user_email')
                and current_order.get('amount') == fare * 100
            ):
                order = current_order
            else:
                booking_ref = f"bus-{token_hex(8)}"
                try:
                    order = create_razorpay_order(fare, booking_ref)
                except Exception:
                    app.logger.exception("Razorpay order creation failed")
                    flash("We could not start Razorpay checkout. Please try again.")
                    return redirect(url_for('payment'))
                order = {
                    'id': order['id'],
                    'amount': order['amount'],
                    'currency': order['currency'],
                    'booking_ref': booking_ref,
                    'bus_key': bus_key,
                    'seat_numbers': seat_numbers,
                    'passenger_email': session.get('user_email'),
                }
                session['razorpay_order'] = order
            return render_template(
                'payment.html',
                seat_numbers=seat_numbers,
                fare=fare,
                razorpay_configured=True,
                razorpay_key_id=app.config['RAZORPAY_KEY_ID'],
                order_id=order['id'],
                amount=order['amount'],
                currency=order['currency'],
            )

        if has_razorpay_key:
            flash("Online payment is configured. Complete Razorpay checkout to confirm this booking.")
            return redirect(url_for('payment'))

        if not confirm_booking():
            session.pop('last_booking', None)
            flash("One or more selected seats were just booked. Please choose again.")
            return redirect(url_for('booking'))
        session.pop('last_booking', None)
        session.pop('razorpay_order', None)
        return redirect(url_for('home'))

    return render_template(
        'payment.html',
        seat_numbers=seat_numbers,
        fare=fare,
        razorpay_configured=razorpay_configured,
        demo_mode=not has_razorpay_key,
    )

@app.route('/track', methods=['GET', 'POST'])
def track():
    bus_services = get_bus_services()
    selected_service = request.args.get('service', '')
    if selected_service not in {get_bus_key(bus) for bus in bus_services}:
        selected_service = ''
    status = None
    if request.method == 'POST':
        bus_name = request.form['bus_name']
        bus_type = request.form['bus_type']
        bus_start_time = request.form['bus_start_time']
        bus_key = tracking_bus_key(bus_name, bus_type, bus_start_time)
        location_tuple = read_location(bus_key)
        location = location_tuple[2] if location_tuple else "Location not updated yet"
        timestamp = location_tuple[3] if location_tuple else "N/A"
        status = f"Bus {bus_name} ({bus_type}), Start Time {bus_start_time} currently at: {location} (Updated at: {timestamp})"
    return render_template(
        'track.html',
        bus_services=bus_services,
        selected_service=selected_service,
        status=status,
    )

@app.route('/booking', methods=['GET', 'POST'])
def booking():
    if 'user_email' not in session:
        flash("Please sign in to book a seat.")
        return redirect(url_for('signin'))
    bus_services = get_bus_services()
    service_by_key = {get_bus_key(bus): bus for bus in bus_services}
    booked = []
    selected_key = None
    selected_bus = None
    if request.method == 'GET':
        selected_key = request.args.get('service', '')
        selected_bus = service_by_key.get(selected_key)
        if selected_bus is None:
            selected_key = None
        else:
            booked = [
                booking.seat_number
                for booking in BookingSeat.query.filter_by(bus_key=selected_key).all()
            ]
    if request.method == 'POST':
        action = request.form.get('action')
        if action == "select_bus":
            selected_key = request.form.get('selected_bus', '')
            selected_bus = service_by_key.get(selected_key)
            if selected_bus is None:
                flash("Please choose a valid bus service.")
                return redirect(url_for('booking'))
            booked = [
                booking.seat_number
                for booking in BookingSeat.query.filter_by(bus_key=selected_key).all()
            ]
            return render_template(
                'booking.html',
                bus_services=bus_services,
                selected_key=selected_key,
                selected_bus=selected_bus,
                seat_rows=get_seat_map(),
                booked=booked,
            )
        elif action == "book_seat":
            selected_key = request.form.get('selected_key', '')
            selected_bus = service_by_key.get(selected_key)
            if selected_bus is None:
                flash("Please choose a valid bus service.")
                return redirect(url_for('booking'))
            try:
                seats_selected = [int(s) for s in request.form.getlist('seat_numbers')]
            except ValueError:
                flash("Please choose valid seats.")
                return redirect(url_for('booking'))
            valid_seats = {seat for row in get_seat_map() for seat in row if seat is not None}
            if (not seats_selected or any(seat not in valid_seats for seat in seats_selected)
                    or len(set(seats_selected)) != len(seats_selected)):
                flash("Please select at least one valid seat.")
                booked = [
                    booking.seat_number
                    for booking in BookingSeat.query.filter_by(bus_key=selected_key).all()
                ]
                return render_template('booking.html', bus_services=bus_services, selected_key=selected_key, selected_bus=selected_bus, seat_rows=get_seat_map(), booked=booked)
            booked_seats = {
                booking.seat_number
                for booking in BookingSeat.query.filter_by(bus_key=selected_key).all()
            }
            already_booked = [seat for seat in seats_selected if seat in booked_seats]
            if already_booked:
                flash(f"Seats already booked: {already_booked}")
                booked = list(booked_seats)
                return render_template('booking.html', bus_services=bus_services, selected_key=selected_key, selected_bus=selected_bus, seat_rows=get_seat_map(), booked=booked)
            else:
                session['last_booking'] = {'bus_key': selected_key, 'seat_numbers': seats_selected}
                return redirect(url_for('payment'))
    if selected_bus:
        return render_template(
            'booking.html',
            bus_services=bus_services,
            selected_key=selected_key,
            selected_bus=selected_bus,
            seat_rows=get_seat_map(),
            booked=booked,
        )
    return render_template('booking.html', bus_services=bus_services)

@app.route('/timetable', methods=['GET', 'POST'])
def timetable():
    all_services = get_bus_services()
    filters = {
        'start_point': request.args.get('start_point', '').strip(),
        'end_point': request.args.get('end_point', '').strip(),
        'bus_name': request.args.get('bus_name', '').strip(),
        'bus_type': request.args.get('bus_type', '').strip(),
        'bus_start_time': request.args.get('bus_start_time', '').strip(),
    }
    buses = [
        bus for bus in all_services
        if (not filters['start_point'] or bus['start_point'] == filters['start_point'])
        and (not filters['end_point'] or bus['end_point'] == filters['end_point'])
        and (not filters['bus_name'] or bus['bus_name'] == filters['bus_name'])
        and (not filters['bus_type'] or bus['bus_type'] == filters['bus_type'])
        and (not filters['bus_start_time'] or bus['bus_start_time'] == filters['bus_start_time'])
    ]
    return render_template(
        'timetable.html',
        buses=buses,
        filters=filters,
        start_points=sorted({bus['start_point'] for bus in all_services}),
        end_points=sorted({bus['end_point'] for bus in all_services}),
        bus_names=sorted({bus['bus_name'] for bus in all_services}),
        bus_types=sorted({bus['bus_type'] for bus in all_services}),
        bus_times=sorted(
            {bus['bus_start_time'] for bus in all_services},
            key=lambda time: datetime.strptime(time, '%I:%M %p').time(),
        ),
    )

if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}
    app.run(debug=debug)