#!/bin/bash
# Titan Permit Scraper — Mini PC Setup
# Run once: bash setup_minipc.sh

set -e

echo "Installing Python dependencies..."
pip3 install requests openpyxl supabase python-dotenv

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
  echo "Creating .env — fill in your Supabase credentials"
  cat > .env <<EOF
SUPABASE_URL=https://yfscfuyxbluidykmpjod.supabase.co
SUPABASE_SERVICE_KEY=YOUR_SERVICE_KEY_HERE
EOF
  echo "Edit .env with your SUPABASE_SERVICE_KEY before running the scraper"
fi

# Set up daily cron at 6:00 AM
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_JOB="0 6 * * * cd $SCRIPT_DIR && /usr/bin/python3 permit_scraper.py >> /tmp/titan_permits.log 2>&1"

# Add to crontab if not already there
(crontab -l 2>/dev/null | grep -v permit_scraper; echo "$CRON_JOB") | crontab -

echo ""
echo "Done. Scraper will run every day at 6:00 AM."
echo "Run manually anytime: python3 permit_scraper.py"
echo "View logs: tail -f /tmp/titan_permits.log"
