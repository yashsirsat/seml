import requests
import time
import csv

# Fill these details as per your Flask app logic
url = "http://127.0.0.1:5000/api/auto_update_location"
session = requests.Session()

# Load all buses from CSV
buses = []
with open('msrtc_bus_data_sample.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        buses.append({
            "bus_name": row['bus_name'],
            "bus_type": row['bus_type'],
            "bus_start_time": row['bus_start_time']
        })

# Track which buses have been manually started by station master
active_buses = set()

def check_started_buses():
    """Check which buses have been manually started by querying the Flask app"""
    try:
        # This is a simplified approach - in production, you'd have a proper API endpoint
        # For now, we'll assume buses are started when they have location data
        response = session.get("http://127.0.0.1:5000/api/get_started_buses")
        if response.status_code == 200:
            data = response.json()
            active_buses.clear()
            active_buses.update(data.get('started_buses', []))
    except:
        pass  # If endpoint doesn't exist, continue with current active_buses

while True:
    # Check for newly started buses
    check_started_buses()

    for bus in buses:
        bus_key = f"{bus['bus_name']}_{bus['bus_type']}_{bus['bus_start_time']}"

        # Only update buses that have been manually started by station master
        if bus_key in active_buses:
            # Fetch current location from the Flask app API
            try:
                location_response = session.get(f"http://127.0.0.1:5000/bus_location_api?bus_name={bus['bus_name']}&bus_type={bus['bus_type']}&bus_start_time={bus['bus_start_time']}")
                if location_response.status_code == 200:
                    loc_data = location_response.json()
                    if loc_data['lat'] != "Location not available":
                        lat = float(loc_data['lat'])
                        lon = float(loc_data['lon'])
                    else:
                        lat, lon = 18.52, 73.85  # Default to Pune
                else:
                    lat, lon = 18.52, 73.85
            except Exception as e:
                print(f"Error fetching location for {bus_key}: {e}")
                lat, lon = 18.52, 73.85

            # Add small random GPS drift to simulate real movement (~100m)
            import random
            lat += random.uniform(-0.001, 0.001)
            lon += random.uniform(-0.001, 0.001)
            
            current_location = f"{lat},{lon}"
            payload = {
                "bus_name": bus["bus_name"],
                "bus_type": bus["bus_type"],
                "bus_start_time": bus["bus_start_time"],
                "location": current_location
            }
            response = session.post(url, json=payload)
            print(f"Updated {bus['bus_name']} ({bus['bus_type']}) {bus['bus_start_time']}: {current_location} | Status: {response.status_code}")

    time.sleep(60)  # Update every 1 minute
