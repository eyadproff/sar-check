#!/usr/bin/env python3
"""
SAR (Saudi Arabia Railways) Ticket Availability Monitor

Monitors train ticket availability for:
- Riyadh → Qurayyat: March 3-20, 2025
- Qurayyat → Riyadh: March 23 - April 2, 2025

Sends email notification when tickets become available.
"""

import os
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
import json

# Configuration
CONFIG = {
    # Route 1: Riyadh to Qurayyat
    "outbound": {
        "from_station": "RIY",      # Riyadh
        "to_station": "QUR",        # Qurayyat (may need adjustment)
        "from_name": "Riyadh",
        "to_name": "Qurayyat",
        "start_date": "2025-03-03",
        "end_date": "2025-03-20",
        "direction": "N"            # North
    },
    # Route 2: Qurayyat to Riyadh
    "return": {
        "from_station": "QUR",      # Qurayyat
        "to_station": "RIY",        # Riyadh
        "from_name": "Qurayyat",
        "to_name": "Riyadh",
        "start_date": "2025-03-23",
        "end_date": "2025-04-02",
        "direction": "N"            # North
    }
}

# Alternative station codes to try if QUR doesn't work
QURAYYAT_CODES = ["QUR", "QRY", "QURAYYAT", "JOF"]  # JOF = Al Jawf region

def build_search_url(from_station: str, to_station: str, date: str, direction: str = "N") -> str:
    """Build SAR ticket search URL"""
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


def generate_dates(start_date: str, end_date: str) -> list[str]:
    """Generate list of dates between start and end (inclusive)"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


async def check_availability(page, url: str, route_name: str, date: str) -> dict | None:
    """
    Check if tickets are available for a specific date
    Returns dict with trip info if available, None otherwise
    """
    try:
        print(f"  Checking {route_name} on {date}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
        # Wait for page to load
        await page.wait_for_timeout(3000)
        
        # Check for "no trips" message or error
        content = await page.content()
        page_text = await page.inner_text("body")
        
        # Common indicators of no availability
        no_availability_indicators = [
            "no trips available",
            "no trains available", 
            "no results",
            "لا توجد رحلات",  # Arabic: no trips
            "غير متوفر",      # Arabic: not available
            "sold out",
            "no seats available"
        ]
        
        for indicator in no_availability_indicators:
            if indicator.lower() in page_text.lower():
                return None
        
        # Look for trip cards/results
        # SAR typically shows trips in cards with departure times and prices
        trip_selectors = [
            ".trip-card",
            ".journey-card", 
            ".train-result",
            "[class*='trip']",
            "[class*='journey']",
            ".available-trip"
        ]
        
        for selector in trip_selectors:
            try:
                trips = await page.query_selector_all(selector)
                if trips and len(trips) > 0:
                    # Found trips - extract info
                    trip_info = {
                        "date": date,
                        "route": route_name,
                        "url": url,
                        "count": len(trips)
                    }
                    
                    # Try to get more details
                    try:
                        first_trip = trips[0]
                        trip_text = await first_trip.inner_text()
                        trip_info["details"] = trip_text[:500]  # First 500 chars
                    except:
                        pass
                    
                    return trip_info
            except:
                continue
        
        # Alternative: check if there are any clickable book buttons
        book_buttons = await page.query_selector_all("button:has-text('Book'), button:has-text('احجز'), a:has-text('Book')")
        if book_buttons and len(book_buttons) > 0:
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "count": len(book_buttons),
                "details": "Book buttons found - tickets likely available"
            }
        
        # Check for price elements (usually indicates availability)
        price_elements = await page.query_selector_all("[class*='price'], [class*='fare'], .sar-price")
        if price_elements and len(price_elements) > 0:
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "count": len(price_elements),
                "details": "Price elements found - tickets likely available"
            }
            
        return None
        
    except Exception as e:
        print(f"    Error checking {date}: {str(e)}")
        return None


async def discover_station_codes(page) -> dict:
    """Try to discover correct station codes from SAR website"""
    print("Attempting to discover station codes...")
    
    try:
        await page.goto("https://tickets.sar.com.sa/Booking", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Try to find station dropdowns and extract codes
        # This is a best-effort attempt
        station_data = {}
        
        # Look for station select elements
        selects = await page.query_selector_all("select, [role='listbox']")
        for select in selects:
            options = await select.query_selector_all("option")
            for option in options:
                value = await option.get_attribute("value")
                text = await option.inner_text()
                if value and text:
                    station_data[text.strip()] = value
        
        if station_data:
            print(f"Found station codes: {json.dumps(station_data, indent=2)}")
            
        return station_data
    except Exception as e:
        print(f"Could not discover station codes: {e}")
        return {}


def send_email(available_trips: list[dict]):
    """Send email notification about available tickets"""
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    notify_email = os.environ.get("NOTIFY_EMAIL", sender_email)
    
    if not sender_email or not sender_password:
        print("Email credentials not configured. Printing results instead:")
        for trip in available_trips:
            print(f"\n🎫 TICKETS AVAILABLE!")
            print(f"   Route: {trip['route']}")
            print(f"   Date: {trip['date']}")
            print(f"   URL: {trip['url']}")
            if 'details' in trip:
                print(f"   Details: {trip['details'][:200]}")
        return
    
    # Build email content
    subject = f"🚂 SAR Tickets Available! ({len(available_trips)} trips found)"
    
    body_html = """
    <html>
    <body style="font-family: Arial, sans-serif;">
    <h2 style="color: #2e7d32;">🎫 SAR Train Tickets Available!</h2>
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
    
    body_html += """
    </table>
    <p style="margin-top: 20px; color: #666;">
        <strong>Note:</strong> Book quickly as tickets may sell out!
    </p>
    </body>
    </html>
    """
    
    # Plain text version
    body_text = "SAR Train Tickets Available!\n\n"
    for trip in available_trips:
        body_text += f"Route: {trip['route']}\n"
        body_text += f"Date: {trip['date']}\n"
        body_text += f"Link: {trip['url']}\n\n"
    
    # Create message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = notify_email
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    
    # Send email
    try:
        # Try Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, notify_email, msg.as_string())
        print(f"✅ Email sent successfully to {notify_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        # Try alternative SMTP
        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, notify_email, msg.as_string())
            print(f"✅ Email sent successfully (TLS) to {notify_email}")
        except Exception as e2:
            print(f"❌ Failed to send email (TLS): {e2}")


async def main():
    print("=" * 60)
    print("SAR Ticket Availability Monitor")
    print(f"Started at: {datetime.now().isoformat()}")
    print("=" * 60)
    
    available_trips = []
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        
        # Optional: Try to discover station codes first
        # await discover_station_codes(page)
        
        # Check outbound trips (Riyadh → Qurayyat)
        print("\n📍 Checking OUTBOUND: Riyadh → Qurayyat")
        print(f"   Date range: {CONFIG['outbound']['start_date']} to {CONFIG['outbound']['end_date']}")
        
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
            
            result = await check_availability(
                page, 
                url, 
                f"{CONFIG['outbound']['from_name']} → {CONFIG['outbound']['to_name']}",
                date
            )
            
            if result:
                available_trips.append(result)
                print(f"    ✅ AVAILABLE on {date}!")
            else:
                print(f"    ❌ Not available on {date}")
            
            # Small delay between requests to be respectful
            await page.wait_for_timeout(2000)
        
        # Check return trips (Qurayyat → Riyadh)
        print("\n📍 Checking RETURN: Qurayyat → Riyadh")
        print(f"   Date range: {CONFIG['return']['start_date']} to {CONFIG['return']['end_date']}")
        
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
            
            result = await check_availability(
                page,
                url,
                f"{CONFIG['return']['from_name']} → {CONFIG['return']['to_name']}",
                date
            )
            
            if result:
                available_trips.append(result)
                print(f"    ✅ AVAILABLE on {date}!")
            else:
                print(f"    ❌ Not available on {date}")
            
            await page.wait_for_timeout(2000)
        
        await browser.close()
    
    # Summary and notification
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if available_trips:
        print(f"\n🎉 Found {len(available_trips)} available trip(s)!")
        send_email(available_trips)
    else:
        print("\n😔 No tickets available at this time.")
    
    print(f"\nFinished at: {datetime.now().isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
