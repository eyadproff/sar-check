# SAR Ticket Availability Monitor 🚂

Automated monitoring for Saudi Arabia Railways (SAR) train ticket availability.

## Your Trip Configuration

| Direction | Route | Date Range |
|-----------|-------|------------|
| **Outbound** | Riyadh → Qurayyat | March 3-20, 2025 |
| **Return** | Qurayyat → Riyadh | March 23 - April 2, 2025 |

## Setup Instructions

### 1. Create a GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Create a **public** repository (free unlimited Actions minutes)
3. Name it something like `sar-monitor`

### 2. Add the Files

Upload these files to your repository:
```
sar-monitor/
├── .github/
│   └── workflows/
│       └── sar-monitor.yml
├── monitor.py
└── README.md
```

### 3. Configure Email Secrets

Go to your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these secrets:

| Secret Name | Value |
|-------------|-------|
| `SENDER_EMAIL` | Your Gmail address (e.g., `your.email@gmail.com`) |
| `SENDER_PASSWORD` | Gmail App Password (see below) |
| `NOTIFY_EMAIL` | Email to receive notifications (can be same as sender) |

### 4. Create Gmail App Password

Since Gmail requires an App Password for third-party apps:

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. **Security** → **2-Step Verification** (enable if not already)
3. **Security** → **App passwords**
4. Generate a new app password for "Mail"
5. Copy the 16-character password (no spaces)
6. Use this as `SENDER_PASSWORD`

### 5. Enable GitHub Actions

1. Go to repository → **Actions** tab
2. Click "I understand my workflows, go ahead and enable them"

### 6. Test the Workflow

1. Go to **Actions** → **SAR Ticket Availability Monitor**
2. Click **Run workflow** → **Run workflow**
3. Watch the logs to verify it's working

## How It Works

- ⏰ Runs every **30 minutes** automatically
- 🔍 Checks all dates in your specified ranges
- 📧 Sends email notification when tickets are found
- 🌐 Uses Playwright (headless browser) to render the SAR booking page

## Customization

### Change Date Ranges

Edit `monitor.py` and update the `CONFIG` dictionary:

```python
CONFIG = {
    "outbound": {
        "start_date": "2025-03-03",  # Change these
        "end_date": "2025-03-20",
        ...
    },
    "return": {
        "start_date": "2025-03-23",  # Change these
        "end_date": "2025-04-02",
        ...
    }
}
```

### Change Check Frequency

Edit `.github/workflows/sar-monitor.yml`:

```yaml
schedule:
  - cron: '*/15 * * * *'  # Every 15 minutes
  - cron: '0 * * * *'     # Every hour
  - cron: '0 */6 * * *'   # Every 6 hours
```

## ⚠️ Important Notes

### Station Codes
The script uses `QUR` for Qurayyat. If tickets aren't being detected:
1. Visit [tickets.sar.com.sa](https://tickets.sar.com.sa)
2. Open browser DevTools (F12) → Network tab
3. Search for Riyadh → Qurayyat
4. Check the URL for the correct station code
5. Update `CONFIG` in `monitor.py`

Possible Qurayyat codes: `QUR`, `QRY`, `QURAYYAT`, `JOF`

### Rate Limiting
- SAR may block requests if too frequent
- The script includes 2-second delays between checks
- If blocked, increase the cron interval

### GitHub Actions Limits
- Public repos: **Unlimited** free minutes
- Private repos: **2,000 minutes/month** free
- Scheduled jobs may be delayed during high load

## Troubleshooting

### "No tickets available" but they exist
1. Station codes might be wrong
2. SAR may have changed their website structure
3. Check Actions logs for errors

### Email not sending
1. Verify Gmail App Password is correct
2. Check spam folder
3. Ensure 2-Step Verification is enabled

### Workflow not running
1. GitHub may throttle scheduled workflows
2. Use manual trigger to test
3. Check if Actions is enabled for the repo

## Local Testing

```bash
# Install dependencies
pip install playwright aiohttp
playwright install chromium

# Set environment variables (optional for email)
export SENDER_EMAIL="your@gmail.com"
export SENDER_PASSWORD="your-app-password"
export NOTIFY_EMAIL="notify@email.com"

# Run the script
python monitor.py
```

## License

MIT - Use freely for personal purposes.

---

**Note**: This is an unofficial tool and not affiliated with SAR. Use responsibly and respect their terms of service.
