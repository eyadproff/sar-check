#!/usr/bin/env python3
"""
SAR (Saudi Arabia Railways) Ticket Availability Monitor

Monitors train ticket availability for:
- Riyadh to Qurayyat: March 3-20, 2025
- Qurayyat to Riyadh: March 23 - April 2, 2025
"""

import os
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
import json

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
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        page_text = await page.inner_text("body")
        
        no_availability_indicators = [
            "no trips available",
            "no trains available", 
            "no results",
            "sold out",
            "no seats available"
        ]
        
        for indicator in no_availability_indicators:
            if indicator.lower() in page_text.lower():
                return None
        
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
                    trip_info = {
                        "date": date,
                        "route": route_name,
                        "url": url,
                        "count": len(trips)
                    }
                    try:
                        first_trip = trips[0]
                        trip_text = await first_trip.inner_text()
                        trip_info["details"] = trip_text[:500]
                    except:
                        pass
                    return trip_info
            except:
                continue
        
        book_buttons = await page.query_selector_all("button:has-text('Book'), a:has-text('Book')")
        if book_buttons and len(book_buttons) > 0:
            return {
                "date": date,
                "route": route_name,
                "url": url,
                "count": len(book_buttons),
                "details": "Book buttons found - tickets likely available"
            }
        
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


def send_email(available_trips):
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    notify_email = os.environ.get("NOTIFY_EMAIL", sender_email)
    
    if not sender_email or not sender_password:
        print("Email credentials not configured. Printing results instead:")
        for trip in available_trips:
            print(f"\nTICKETS AVAILABLE!")
            print(f"   Route: {trip['route']}")
            print(f"   Date: {trip['date']}")
            print(f"   URL: {trip['url']}")
            if 'details' in trip:
                print(f"   Details: {trip['details'][:200]}")
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
    
    body_html += """
    </table>
    <p style="margin-top: 20px; color: #666;">
        <strong>Note:</strong> Book quickly as tickets may sell out!
    </p>
    </body>
    </html>
    """
    
    body_text = "SAR Train Tickets Available!\n\n"
    for trip in available_trips:
        body_text += f"Route: {trip['route']}\n"
        body_text += f"Date: {trip['date']}\n"
        body_text += f"Link: {trip['url']}\n\n"
    
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
        print(f"Email sent successfully to {notify_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, notify_email, msg.as_string())
            print(f"Email sent successfully (TLS) to {notify_email}")
        except Exception as e2:
            print(f"Failed to send email (TLS): {e2}")


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
            viewport={"width": 1280, "height": 720},
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
                print(f"    AVAILABLE on {date}!")
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
                print(f"    AVAILABLE on {date}!")
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
