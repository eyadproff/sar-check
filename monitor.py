#!/usr/bin/env python3
import os
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

CONFIG = {
    "outbound": {
        "from_station": "RIY",
        "to_station": "QUR",
        "from_name": "Riyadh",
        "to_name": "Qurayyat",
        "start_date": "2025-03-03",
        "end_date": "2025-03-20",
        "direction": "N"
    },
    "return": {
        "from_station": "QUR",
        "to_station": "RIY",
        "from_name": "Qurayyat",
        "to_name": "Riyadh",
        "start_date": "2025-03-23",
        "end_date": "2025-04-02",
        "direction": "N"
    }
}


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


def generate_dates(start_date, end_date):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


async def check_availability(page, url, route_name, date):
    try:
        print(f"  Checking {route_name} on {date}...")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        
        # Wait longer for dynamic content to load
        await page.wait_for_timeout(5000)
        
        # Get page content
        page_text = await page.inner_text("body")
        
        # Debug: print part of page content
        print(f"    Page loaded, checking content...")
        
        # Check for "trips available" text - this is what SAR shows
        if "trips available" in page_text.lower():
            print(f"    Found 'trips available' text!")
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "details": "Trips available"
            }
        
        # Check for price indicators (SAR shows prices like "185", "520", "1560")
        # Look for Economy, Business, Private Cabin prices
        if "economy" in page_text.lower() and ("185" in page_text or "sar" in page_text.lower()):
            print(f"    Found Economy class pricing!")
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "details": "Economy tickets found"
            }
        
        # Check for train numbers (e.g., "Train 76")
        if "train" in page_text.lower() and any(f"train {i}" in page_text.lower() for i in range(1, 200)):
            print(f"    Found train listing!")
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "details": "Train found"
            }
        
        # Check for time patterns like "21:00" or "07:33"
        import re
        time_pattern = re.compile(r'\d{2}:\d{2}')
        times_found = time_pattern.findall(page_text)
        if len(times_found) >= 2:  # At least departure and arrival time
            print(f"    Found time schedule!")
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "details": f"Schedule times found: {times_found[:2]}"
            }
        
        # Check for "Select Outbound Trip" which appears when trips exist
        if "select outbound trip" in page_text.lower() or "select return trip" in page_text.lower():
            print(f"    Found trip selection page!")
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "details": "Trip selection available"
            }
        
        # Check for specific no-availability messages
        no_availability = [
            "no trips available",
            "no trains available",
            "no trips found",
            "sorry",
            "not available"
        ]
        
        for phrase in no_availability:
            if phrase in page_text.lower():
                print(f"    No availability: found '{phrase}'")
                return None
        
        # If we got here and page has substantial content, might be available
        # Check for any SAR-specific elements
        try:
            # Look for trip cards or booking elements
            trip_elements = await page.query_selector_all("[class*='trip'], [class*='journey'], [class*='train'], [class*='schedule']")
            if trip_elements and len(trip_elements) > 0:
                print(f"    Found {len(trip_elements)} trip-related elements")
                return {
                    "date": date,
                    "route": route_name,
                    "url": url,
                    "details": f"Found {len(trip_elements)} trip elements"
                }
            
            # Look for price buttons/elements
            price_elements = await page.query_selector_all("[class*='price'], [class*='fare'], [class*='cost']")
            if price_elements and len(price_elements) > 0:
                print(f"    Found {len(price_elements)} price elements")
                return {
                    "date": date,
                    "route": route_name,
                    "url": url,
                    "details": f"Found {len(price_elements)} price elements"
                }
                
        except Exception as e:
            print(f"    Element check error: {e}")
        
        print(f"    No clear availability indicators found")
        return None
        
    except Exception as e:
        print(f"    Error checking {date}: {str(e)}")
        return None


def send_email(available_trips):
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    notify_email = os.environ.get("NOTIFY_EMAIL", sender_email)
    
    if not sender_email or not sender_password:
        print("Email credentials not configured. Printing results:")
        for trip in available_trips:
            print(f"TICKETS AVAILABLE!")
            print(f"   Route: {trip['route']}")
            print(f"   Date: {trip['date']}")
            print(f"   URL: {trip['url']}")
        return
    
    subject = f"SAR Tickets Available! ({len(available_trips)} trips found)"
    
    body_html = """
    <html>
    <body style="font-family: Arial, sans-serif;">
    <h2 style="color: #2e7d32;">SAR Train Tickets Available!</h2>
    <p>The following train tickets are now available:</p>
    <table style="border-collapse: collapse; width: 100%;">
        <tr style="background-color: #e8f5e9;">
            <th style="padding: 10px; border: 1px solid #ddd;">Route</th>
            <th style="padding: 10px; border: 1px solid #ddd;">Date</th>
            <th style="padding: 10px; border: 1px solid #ddd;">Link</th>
        </tr>
    """
    
    for trip in available_trips:
        body_html += f"""
        <tr>
            <td style="padding: 10px; border: 1px solid #ddd;">{trip['route']}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">{trip['date']}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">
                <a href="{trip['url']}" style="color: #1976d2;">Book Now</a>
            </td>
        </tr>
        """
    
    body_html += "</table></body></html>"
    
    body_text = "SAR Train Tickets Available!\n\n"
    for trip in available_trips:
        body_text += f"Route: {trip['route']}\nDate: {trip['date']}\nLink: {trip['url']}\n\n"
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = notify_email
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, notify_email, msg.as_string())
        print(f"Email sent to {notify_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")


async def main():
    print("=" * 60)
    print("SAR Ticket Availability Monitor")
    print(f"Started at: {datetime.now().isoformat()}")
    print("=" * 60)
    
    available_trips = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        
        print("\nChecking OUTBOUND: Riyadh to Qurayyat")
        print(f"Date range: {CONFIG['outbound']['start_date']} to {CONFIG['outbound']['end_date']}")
        
        outbound_dates = generate_dates(
            CONFIG['outbound']['start_date'],
            CONFIG['outbound']['end_date']
        )
        
        for date in outbound_dates:
            url = build_search_url(
                CONFIG['outbound']['from_station'],
                CONFIG['outbound']['to_station'],
                date,
                CONFIG['outbound']['direction']
            )
            
            route_name = CONFIG['outbound']['from_name'] + " to " + CONFIG['outbound']['to_name']
            result = await check_availability(page, url, route_name, date)
            
            if result:
                available_trips.append(result)
                print(f"    >>> AVAILABLE on {date}!")
            else:
                print(f"    Not available on {date}")
            
            await page.wait_for_timeout(2000)
        
        print("\nChecking RETURN: Qurayyat to Riyadh")
        print(f"Date range: {CONFIG['return']['start_date']} to {CONFIG['return']['end_date']}")
        
        return_dates = generate_dates(
            CONFIG['return']['start_date'],
            CONFIG['return']['end_date']
        )
        
        for date in return_dates:
            url = build_search_url(
                CONFIG['return']['from_station'],
                CONFIG['return']['to_station'],
                date,
                CONFIG['return']['direction']
            )
            
            route_name = CONFIG['return']['from_name'] + " to " + CONFIG['return']['to_name']
            result = await check_availability(page, url, route_name, date)
            
            if result:
                available_trips.append(result)
                print(f"    >>> AVAILABLE on {date}!")
            else:
                print(f"    Not available on {date}")
            
            await page.wait_for_timeout(2000)
        
        await browser.close()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if available_trips:
        print(f"\nFound {len(available_trips)} available trip(s)!")
        send_email(available_trips)
    else:
        print("\nNo tickets available at this time.")
    
    print(f"\nFinished at: {datetime.now().isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
