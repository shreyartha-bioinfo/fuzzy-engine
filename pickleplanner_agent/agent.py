"""
PicklePlanner Court Reservation Agent
Logs in and books a court automatically based on config.py preferences.
"""

import sys
import logging
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pickleplanner_agent.log"),
    ],
)
log = logging.getLogger(__name__)

BASE_URL = "https://www.pickleplanner.com"
LOGIN_URL = f"{BASE_URL}/login"


def run():
    target_date = datetime.now() + timedelta(days=config.DAYS_AHEAD)
    if target_date.weekday() not in config.TARGET_DAYS:
        log.info(
            "Target date %s (weekday %d) is not in TARGET_DAYS %s — skipping.",
            target_date.strftime("%Y-%m-%d"),
            target_date.weekday(),
            config.TARGET_DAYS,
        )
        return

    log.info("Starting reservation agent for %s", target_date.strftime("%Y-%m-%d"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=config.HEADLESS, slow_mo=config.SLOW_MO)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        try:
            _login(page)
            booked = _book_courts(page, target_date)
            if booked:
                log.info("Successfully booked %d court(s).", booked)
            else:
                log.warning("No courts were booked — check availability or config.")
        except Exception as exc:
            log.error("Agent failed: %s", exc, exc_info=True)
            page.screenshot(path="error_screenshot.png")
            log.info("Screenshot saved to error_screenshot.png")
            raise
        finally:
            browser.close()


def _login(page):
    log.info("Navigating to login page …")
    page.goto(LOGIN_URL, wait_until="networkidle")

    # Fill credentials — selectors may need adjustment if the site changes
    page.fill('input[type="email"], input[name="email"]', config.EMAIL)
    page.fill('input[type="password"], input[name="password"]', config.PASSWORD)
    page.click('button[type="submit"], input[type="submit"]')

    # Wait for redirect away from login
    try:
        page.wait_for_url(lambda url: "login" not in url, timeout=10_000)
        log.info("Login successful.")
    except PWTimeout:
        raise RuntimeError(
            "Still on login page after submit — check credentials in config.py"
        )


def _book_courts(page, target_date: datetime) -> int:
    """Navigate to the booking/schedule page and attempt to reserve a slot."""
    log.info("Loading schedule page …")

    # PicklePlanner typically uses /schedule or /courts — try both
    for path in ["/schedule", "/courts", "/reservations", "/book"]:
        page.goto(f"{BASE_URL}{path}", wait_until="networkidle")
        if page.url.endswith(path) or path.lstrip("/") in page.url:
            break
    else:
        raise RuntimeError("Could not find the booking/schedule page.")

    # Navigate to the target date if a date-picker is present
    _navigate_to_date(page, target_date)

    booked = 0
    for preferred_time in config.PREFERRED_TIMES:
        if booked >= config.MAX_BOOKINGS:
            break
        slot = _find_slot(page, preferred_time)
        if slot:
            log.info("Found slot at %s — attempting to reserve …", preferred_time)
            if _reserve_slot(page, slot):
                booked += 1
                log.info("Reservation confirmed for %s.", preferred_time)
        else:
            log.info("No available slot found at %s.", preferred_time)

    return booked


def _navigate_to_date(page, target_date: datetime):
    """Click forward/back arrows or use a date input to reach the target date."""
    date_str = target_date.strftime("%Y-%m-%d")
    log.info("Navigating to date %s …", date_str)

    # Try a date input first (fastest)
    date_input = page.query_selector('input[type="date"]')
    if date_input:
        date_input.fill(date_str)
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")
        return

    # Some sites append ?date= to the URL
    if "?" not in page.url:
        page.goto(page.url + f"?date={date_str}", wait_until="networkidle")


def _find_slot(page, time_str: str):
    """
    Return the first clickable slot element matching the requested time
    that is NOT already booked/disabled.
    """
    # Common patterns: data-time attribute, visible text containing the time
    selectors = [
        f'[data-time="{time_str}"]',
        f'[data-start="{time_str}"]',
        f'button:has-text("{time_str}")',
        f'td:has-text("{time_str}")',
        f'div:has-text("{time_str}")',
    ]

    for sel in selectors:
        els = page.query_selector_all(sel)
        for el in els:
            if not el.is_visible():
                continue
            # Skip slots already taken (common class names used by booking UIs)
            classes = el.get_attribute("class") or ""
            if any(k in classes for k in ("booked", "reserved", "unavailable", "disabled", "taken")):
                continue
            # Apply facility filter
            if config.FACILITY_FILTER:
                parent_text = el.evaluate("el => el.closest('[data-court], [data-facility], tr, .court')?.textContent ?? ''")
                if config.FACILITY_FILTER.lower() not in parent_text.lower():
                    continue
            return el

    return None


def _reserve_slot(page, slot_element) -> bool:
    """Click the slot and confirm any modal/dialog that appears."""
    slot_element.click()
    page.wait_for_load_state("networkidle")

    # Handle confirmation dialogs / modals
    confirm_selectors = [
        'button:has-text("Confirm")',
        'button:has-text("Reserve")',
        'button:has-text("Book")',
        'button:has-text("Submit")',
        'input[type="submit"]',
    ]
    for sel in confirm_selectors:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            log.info("Clicking confirmation button …")
            btn.click()
            page.wait_for_load_state("networkidle")
            break

    # Check for a success indicator
    success_keywords = ["confirmed", "success", "booked", "reservation", "thank you"]
    page_text = page.inner_text("body").lower()
    return any(kw in page_text for kw in success_keywords)


if __name__ == "__main__":
    run()
