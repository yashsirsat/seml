import csv
import re
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
import reverse_geocoder as rg
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

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

# Mail configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'pccoepune00@gmail.com'
app.config['MAIL_PASSWORD'] = 'zbee gybx fwrs ozam'  # replace with your Gmail app password
mail = Mail(app)

# ----------------- DATABASE MODELS -----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False) # Consider hashing in production!
    role = db.Column(db.String(50), nullable=False)

# Initialize Database
with app.app_context():
    db.create_all()

# ----------------- IN-MEMORY DATA (To be migrated later) -----------------
bookings = {}
bus_locations = {}  # Key: f"{bus_name}_{bus_type}_{start_time}", Value: (lat, lon, location_name, timestamp)
started_buses = set()  # Track buses that have been manually started by station master


# ----------------- HELPER FUNCTIONS -----------------

def get_unique_bus_data():
    bus_names = set()
    bus_types = set()
    bus_times = set()
    with open('msrtc_bus_data_sample.csv', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            bus_names.add(row['bus_name'])
            bus_types.add(row['bus_type'])
            bus_times.add(row['bus_start_time'])
    return sorted(bus_names), sorted(bus_types), sorted(bus_times)

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


# ----------------- ROUTES -----------------

@app.route('/')
def index():
    return redirect(url_for('signin'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        
        if len(password) < 8 or not re.match(r'^[A-Za-z0-9]+$', password):
            flash('Password must be minimum 8 characters and alphanumeric.')
            return render_template('signup.html')
            
        # Check if user already exists in DB
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered.')
            return redirect(url_for('signin'))
            
        # Create new user and save to DB
        new_user = User(name=name, email=email, password=password, role=role)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Signup successful. Please signin.')
        return redirect(url_for('signin'))
    return render_template('signup.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        # Fetch user from DB
        user = User.query.filter_by(email=email).first()
        
        if user and user.password == password:
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
        bus_name = request.form['bus_name']
        bus_type = request.form['bus_type']
        bus_start_time = request.form['bus_start_time']
        location_str = request.form['location']
        try:
            lat, lon = map(float, location_str.split(','))
            location_name = get_location_name((lat, lon))
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bus_key = f"{bus_name}_{bus_type}_{bus_start_time}"
            bus_locations[bus_key] = (lat, lon, location_name, timestamp)
            started_buses.add(bus_key)  # Mark this bus as manually started
            message = f"Bus '{bus_name}' ({bus_type}) at {bus_start_time} location updated to '{location_name}' at {timestamp}. Auto-updates enabled."
        except:
            flash("Invalid latitude/longitude format.")
    return render_template('station_master.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times, message=message)

@app.route('/api/auto_update_location', methods=['POST'])
def api_auto_update_location():
    data = request.get_json()
    bus_name = data['bus_name']
    bus_type = data['bus_type']
    bus_start_time = data.get('bus_start_time', 'N/A')  # Optional for backward compatibility
    location_str = data['location']
    lat, lon = map(float, location_str.split(','))
    location_name = get_location_name((lat, lon))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bus_key = f"{bus_name}_{bus_type}_{bus_start_time}"
    bus_locations[bus_key] = (lat, lon, location_name, timestamp)
    return jsonify({"success": True, "msg": "Location auto-updated!"})

@app.route('/bus_location_api')
def bus_location_api():
    bus_name = request.args.get('bus_name')
    bus_type = request.args.get('bus_type')
    bus_start_time = request.args.get('bus_start_time', 'N/A')
    bus_key = f"{bus_name}_{bus_type}_{bus_start_time}"
    loc_data = bus_locations.get(bus_key, ("Location not available", "N/A", "N/A", "N/A"))
    return jsonify(lat=loc_data[0], lon=loc_data[1], location=loc_data[2], timestamp=loc_data[3])

@app.route('/api/get_started_buses')
def get_started_buses():
    return jsonify(started_buses=list(started_buses))

@app.route('/api/stop_sharing/<bus_key>')
def api_stop_sharing(bus_key):
    """Stop auto-tracking for specific bus"""
    if bus_key in started_buses:
        started_buses.discard(bus_key)
        return jsonify({"success": True, "message": f"Stopped sharing for {bus_key}"})
    else:
        return jsonify({"success": False, "message": f"{bus_key} not active"}), 404

@app.route('/payment', methods=['GET', 'POST'])
def payment():
    last_booking = session.get('last_booking')
    if not last_booking:
        return redirect(url_for('home'))
    seat_numbers = last_booking['seat_numbers']
    fare = 1 * len(seat_numbers)
    if request.method == 'POST':
        user_email = session.get('user_email')
        user_name = session.get('user_name')
        bus_key = last_booking['bus_key']
        loc_data = bus_locations.get(bus_key, ("Not available", "N/A", "N/A", "N/A"))
        loc_name = loc_data[2] if len(loc_data) > 2 else "Not available"
        loc_time = loc_data[3] if len(loc_data) > 3 else "N/A"
        
        # Send confirmation email directly
        if user_email:
            try:
                msg = Message('Bus Booking Confirmation',
                              sender=app.config['MAIL_USERNAME'],
                              recipients=[user_email])
                msg.body = (f"Hello {user_name},\n\nYour bus booking is confirmed.\n"
                            f"Bus: {bus_key}\nSeats: {', '.join(str(s) for s in seat_numbers)}\n"
                            f"Location at booking time: {loc_name}\n"
                            f"Location updated at: {loc_time}\n"
                            f"Total Fare: ₹{fare}\n\nThank you for using MSRTC.")
                mail.send(msg)
                flash("Booking confirmed! Confirmation email sent successfully.")
            except Exception as e:
                flash(f"Booking confirmed but email sending failed: {str(e)}")
        else:
            flash("Booking confirmed!")
        
        session.pop('last_booking', None)
        return redirect(url_for('home'))
    
    return render_template('payment.html', seat_numbers=seat_numbers, fare=fare)

@app.route('/track', methods=['GET', 'POST'])
def track():
    bus_names, bus_types, bus_times = get_unique_bus_data()
    status = None
    if request.method == 'POST':
        bus_name = request.form['bus_name']
        bus_type = request.form['bus_type']
        bus_start_time = request.form['bus_start_time']
        bus_key = f"{bus_name}_{bus_type}_{bus_start_time}"
        location_tuple = bus_locations.get(bus_key, ("Location not updated yet", "N/A", "N/A", "N/A"))
        location = location_tuple[2] if len(location_tuple) > 2 else "Location not updated yet"
        timestamp = location_tuple[3] if len(location_tuple) > 3 else "N/A"
        status = f"Bus {bus_name} ({bus_type}), Start Time {bus_start_time} currently at: {location} (Updated at: {timestamp})"
    return render_template('track.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times, status=status)

@app.route('/booking', methods=['GET', 'POST'])
def booking():
    bus_names, bus_types, bus_times = get_unique_bus_data()
    booked = []
    buses = []
    selected_key = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == "show_buses" or not action:
            selected_name = request.form['bus_name']
            selected_type = request.form['bus_type']
            selected_time = request.form['bus_start_time']
            with open('msrtc_bus_data_sample.csv', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['bus_name'] == selected_name and row['bus_type'] == selected_type and row['bus_start_time'] == selected_time:
                        buses.append(row)
            return render_template('booking.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times, buses=buses)
        elif action == "select_bus":
            selected_bus = request.form['selected_bus']
            selected_key = selected_bus  # Already includes name_type_time
            if selected_key in bookings:
                booked = list(bookings[selected_key])
            return render_template('booking.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times, selected_key=selected_key, seat_rows=get_seat_map(), booked=booked)
        elif action == "book_seat":
            selected_key = request.form['selected_key']
            seats_selected = request.form.getlist('seat_numbers')
            seats_selected = [int(s) for s in seats_selected]
            if selected_key not in bookings:
                bookings[selected_key] = set()
            already_booked = [s for s in seats_selected if s in bookings[selected_key]]
            if already_booked:
                flash(f"Seats already booked: {already_booked}")
                booked = list(bookings[selected_key])
                return render_template('booking.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times, selected_key=selected_key, seat_rows=get_seat_map(), booked=booked)
            else:
                for s in seats_selected:
                    bookings[selected_key].add(s)
                session['last_booking'] = {'bus_key': selected_key, 'seat_numbers': seats_selected}
                return redirect(url_for('payment'))
    return render_template('booking.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times)

@app.route('/timetable', methods=['GET', 'POST'])
def timetable():
    bus_names, bus_types, bus_times = get_unique_bus_data()
    buses = []
    if request.method == 'POST':
        bus_name = request.form.get('bus_name')
        bus_type = request.form.get('bus_type')
        bus_start_time = request.form.get('bus_start_time')
        with open('msrtc_bus_data_sample.csv', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if ((not bus_name or row['bus_name'] == bus_name) and
                    (not bus_type or row['bus_type'] == bus_type) and
                    (not bus_start_time or row['bus_start_time'] == bus_start_time)):
                    buses.append(row)
    else:
        with open('msrtc_bus_data_sample.csv', newline='', encoding='utf-8') as f:
            buses = list(csv.DictReader(f))
    return render_template('timetable.html', bus_names=bus_names, bus_types=bus_types, bus_times=bus_times, buses=buses)

if __name__ == '__main__':
    app.run(debug=True)