#!/usr/bin/env python3
import os
import asyncio
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

# CONFIGURE YOUR DATES HERE
CONFIG = {
    "outbound": {
        "from_station": "RIY",
        "to_station": "QUR",
        "from_name": "Riyadh",
        "to_name": "Qurayyat",
        "start_date": "2026-02-03",
        "end_date": "2026-02-28",
        "direction": "N",
        "weekdays": [2, 3]  # Wednesday=2, Thursday=3
    },
    "return": {
        "from_station": "QUR",
        "to_station": "RIY",
        "from_name": "Qurayyat",
        "to_name": "Riyadh",
        "start_date": "2026-03-20",
        "end_date": "2026-03-28",
        "direction": "N",
        "weekdays": [5]  # Saturday=5
    }
}

# Weekday reference:
# Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6


def build_search_url(from_station, to_station, date, direction="N"):
    base_url = "https://tickets.sar.com.sa/select-trip"
    params = {
        "DepartureStation": from_station,
        "ArrivalStation": to_station,
        "DepartureDateString": date,
        "AdultCount": "1",
        "ChildCount": "0",
        "InfantCount": "0",
        "DisabledCount": "0",
        "CarerCount": "0",
        "passengersCount": "1",
        "Lang": "en",
        "serviceType": "1",
        "WithCarCargo": "false",
        "TripDirection": direction,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base_url}?{query}"


def generate_dates(start_date, end_date, weekdays=None):
    """
    Generate dates between start and end.
    If weekdays is provided, only include those days.
    weekdays: list of integers (Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6)
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        # If weekdays filter is set, only include matching days
        if weekdays is None or current.weekday() in weekdays:
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def get_day_name(date_str):
    """Get day name from date string"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return date.strftime("%A")


async def check_availability(page, url, route_name, date):
    try:
        day_name = get_day_name(date)
        print(f"Checking {route_name} on {date} ({day_name})...")
        
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)
        
        page_text = await page.inner_text("body")
        page_text_lower = page_text.lower()
        
        print(f"  Page snippet: {page_text[:150].replace(chr(10), ' ')}")
        
        # Detection methods based on actual SAR site
        
        # Method 1: "trips available"
        if "trips available" in page_text_lower:
            print(f"  >> FOUND: 'trips available'")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": "trips available"}
        
        # Method 2: Train number pattern
        train_match = re.search(r'train\s+\d+', page_text_lower)
        if train_match:
            print(f"  >> FOUND: '{train_match.group()}'")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": train_match.group()}
        
        # Method 3: Ticket classes
        if "economy" in page_text_lower and "business" in page_text_lower:
            print(f"  >> FOUND: Economy and Business classes")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": "ticket classes"}
        
        # Method 4: Time pattern (HH:MM)
        time_pattern = re.findall(r'\b([01]?[0-9]|2[0-3]):[0-5][0-9]\b', page_text)
        if len(time_pattern) >= 2:
            print(f"  >> FOUND: Times {time_pattern[:4]}")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": f"times: {time_pattern[:2]}"}
        
        # Method 5: Trip selection
        if "select outbound trip" in page_text_lower or "select return trip" in page_text_lower:
            print(f"  >> FOUND: Trip selection")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": "trip selection"}
        
        # Method 6: Price pattern
        if re.search(r'\b(185|520|1560|125|80|90)\b', page_text):
            print(f"  >> FOUND: Price pattern")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": "prices found"}
        
        # Method 7: Night Trip
        if "night trip" in page_text_lower:
            print(f"  >> FOUND: Night Trip")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": "night trip"}
        
        # Method 8: Duration pattern
        if "stops" in page_text_lower and re.search(r'\d+\s*h\s*\d+\s*m', page_text_lower):
            print(f"  >> FOUND: Journey info")
            return {"date": date, "day": day_name, "route": route_name, "url": url, "reason": "journey info"}
        
        print(f"  Not available")
        return None
        
    except Exception as e:
        print(f"  Error: {str(e)[:100]}")
        return None


def send_email(available_trips):
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    notify_email = os.environ.get("NOTIFY_EMAIL", sender_email)
    
    if not sender_email or not sender_password:
        print("\nNo email configured. Available trips:")
        for trip in available_trips:
            print(f"  {trip['date']} ({trip['day']}) - {trip['route']}")
            print(f"    {trip['url']}")
        return
    
    subject = f"SAR Tickets Available! ({len(available_trips)} trips)"
    
    body = "<html><body style='font-family:Arial'>"
    body += "<h2 style='color:green'>SAR Train Tickets Available!</h2>"
    body += "<table border='1' cellpadding='8' style='border-collapse:collapse'>"
    body += "<tr style='background:#e8f5e9'><th>Date</th><th>Day</th><th>Route</th><th>Book</th></tr>"
    
    for trip in available_trips:
        body += f"<tr>"
        body += f"<td><b>{trip['date']}</b></td>"
        body += f"<td>{trip['day']}</td>"
        body += f"<td>{trip['route']}</td>"
        body += f"<td><a href='{trip['url']}'>Book Now</a></td>"
        body += f"</tr>"
    
    body += "</table>"
    body += "<p style='color:#666'>Book quickly - tickets sell fast!</p>"
    body += "</body></html>"
    
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = notify_email
    msg.attach(MIMEText(body, "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, notify_email, msg.as_string())
        print(f"\nEmail sent to {notify_email}")
    except Exception as e:
        print(f"\nEmail failed: {e}")


async def main():
    print("=" * 60)
    print("SAR Ticket Availability Monitor")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    available_trips = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        
        # OUTBOUND: Riyadh to Qurayyat (Wednesdays & Thursdays only)
        outbound_dates = generate_dates(
            CONFIG['outbound']['start_date'],
            CONFIG['outbound']['end_date'],
            CONFIG['outbound']['weekdays']
        )
        
        print(f"\n{'='*40}")
        print(f"OUTBOUND: {CONFIG['outbound']['from_name']} to {CONFIG['outbound']['to_name']}")
        print(f"Dates: {CONFIG['outbound']['start_date']} to {CONFIG['outbound']['end_date']}")
        print(f"Days: Wednesdays & Thursdays only")
        print(f"Total dates to check: {len(outbound_dates)}")
        print(f"{'='*40}")
        
        for date in outbound_dates:
            url = build_search_url(
                CONFIG['outbound']['from_station'],
                CONFIG['outbound']['to_station'],
                date,
                CONFIG['outbound']['direction']
            )
            route = f"{CONFIG['outbound']['from_name']} to {CONFIG['outbound']['to_name']}"
            result = await check_availability(page, url, route, date)
            if result:
                available_trips.append(result)
            await page.wait_for_timeout(3000)
        
        # RETURN: Qurayyat to Riyadh (Saturdays only)
        return_dates = generate_dates(
            CONFIG['return']['start_date'],
            CONFIG['return']['end_date'],
            CONFIG['return']['weekdays']
        )
        
        print(f"\n{'='*40}")
        print(f"RETURN: {CONFIG['return']['from_name']} to {CONFIG['return']['to_name']}")
        print(f"Dates: {CONFIG['return']['start_date']} to {CONFIG['return']['end_date']}")
        print(f"Days: Saturdays only")
        print(f"Total dates to check: {len(return_dates)}")
        print(f"{'='*40}")
        
        for date in return_dates:
            url = build_search_url(
                CONFIG['return']['from_station'],
                CONFIG['return']['to_station'],
                date,
                CONFIG['return']['direction']
            )
            route = f"{CONFIG['return']['from_name']} to {CONFIG['return']['to_name']}"
            result = await check_availability(page, url, route, date)
            if result:
                available_trips.append(result)
            await page.wait_for_timeout(3000)
        
        await browser.close()
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    if available_trips:
        print(f"\nFOUND {len(available_trips)} AVAILABLE TRIPS:")
        for trip in available_trips:
            print(f"  * {trip['date']} ({trip['day']}) - {trip['route']}")
        send_email(available_trips)
    else:
        print("\nNo tickets available at this time.")
    
    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())
