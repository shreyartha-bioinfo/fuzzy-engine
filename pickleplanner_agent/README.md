# PicklePlanner Reservation Agent

Automatically books pickleball courts on [pickleplanner.com](https://www.pickleplanner.com) every day at 6 AM.

## Setup

```bash
cd pickleplanner_agent
pip install -r requirements.txt
playwright install chromium
```

Edit `config.py` with your credentials and booking preferences:

```python
EMAIL = "you@example.com"
PASSWORD = "yourpassword"
TARGET_DAYS = [1, 3, 5]      # Tue, Thu, Sat (0=Mon … 6=Sun)
PREFERRED_TIMES = ["08:00", "09:00"]
DAYS_AHEAD = 1               # Book tomorrow's slot
FACILITY_FILTER = ""         # Leave blank to pick any court
MAX_BOOKINGS = 1
```

## Run manually

```bash
python agent.py
```

## Schedule with cron (6 AM daily)

```bash
crontab -e
```

Add this line (adjust paths):

```
0 6 * * * cd /path/to/fuzzy-engine/pickleplanner_agent && /usr/bin/python3 agent.py >> /tmp/pickleplanner_cron.log 2>&1
```

## Debugging

Set `HEADLESS = False` in `config.py` to watch the browser while it runs.  
On errors, a screenshot is saved to `error_screenshot.png`.

## Notes

- The slot-detection selectors in `agent.py → _find_slot()` may need tuning  
  if PicklePlanner changes their HTML. Run with `HEADLESS = False` to inspect.
- Credentials are stored in plain text in `config.py` — keep the file private  
  and never commit it to a public repo.
