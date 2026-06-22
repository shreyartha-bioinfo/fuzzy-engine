"""
Configuration for the PicklePlanner reservation agent.
Set your credentials and booking preferences here.
"""

# --- Credentials ---
EMAIL = "your_email@example.com"
PASSWORD = "your_password"

# --- Booking preferences ---
# Days of the week to book (0=Monday ... 6=Sunday)
TARGET_DAYS = [1, 3, 5]  # Tue, Thu, Sat

# Preferred time slots in order of priority (24h format strings, e.g. "08:00", "09:30")
PREFERRED_TIMES = ["08:00", "09:00", "10:00"]

# How many days ahead to look for slots (e.g. 1 = book tomorrow's slot)
DAYS_AHEAD = 1

# Facility / location name substring to match (case-insensitive, leave empty to pick first available)
FACILITY_FILTER = ""

# Max courts to book per run
MAX_BOOKINGS = 1

# --- Browser settings ---
HEADLESS = True   # Set False to watch the browser while debugging
SLOW_MO = 0       # Milliseconds between actions (increase when debugging)
