#!/bin/bash
# Tailscale Funnel Setup for Local LLM
# This script exposes your local LM Studio (port 1234) to the internet

set -e

echo "=========================================="
echo "  Tailscale Funnel Setup for Local LLM"
echo "=========================================="
echo ""

# Find Tailscale CLI - macOS app bundle or standalone
if [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
    TAILSCALE="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    echo "📍 Using Tailscale from app bundle"
elif command -v tailscale &> /dev/null; then
    TAILSCALE="tailscale"
    echo "📍 Using standalone Tailscale CLI"
else
    echo "❌ Tailscale is not installed!"
    echo "   Install it from: https://tailscale.com/download"
    exit 1
fi

# Check Tailscale status
echo "📡 Checking Tailscale status..."
if ! $TAILSCALE status &> /dev/null; then
    echo "❌ Tailscale is not running or not logged in!"
    echo "   Make sure Tailscale app is running and you're logged in"
    exit 1
fi

echo "✅ Tailscale is connected"
echo ""

# Get device name
DEVICE_URL=$($TAILSCALE serve status 2>/dev/null | grep "https://" | head -1 | awk '{print $1}' | sed 's/:443//' || echo "")
if [ -z "$DEVICE_URL" ]; then
    DEVICE_NAME=$($TAILSCALE status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Self',{}).get('DNSName','').rstrip('.'))" 2>/dev/null || echo "your-device.ts.net")
    DEVICE_URL="https://$DEVICE_NAME"
fi

echo "📋 Your device URL: $DEVICE_URL"
echo ""

# Check if LM Studio is running on port 1234
echo "🔍 Checking if LM Studio is running on port 1234..."
if curl -s --connect-timeout 2 http://localhost:1234/v1/models > /dev/null 2>&1; then
    echo "✅ LM Studio is running on port 1234"
else
    echo "⚠️  LM Studio doesn't seem to be running on port 1234"
    echo "   Make sure LM Studio is running with the server enabled"
    read -p "   Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# Reset any existing funnel config
echo "🛑 Resetting existing funnel..."
$TAILSCALE serve reset 2>/dev/null || true
$TAILSCALE funnel reset 2>/dev/null || true
sleep 1

# Set up funnel with simple command (new syntax)
echo "🌐 Enabling Funnel..."
$TAILSCALE funnel --bg http://localhost:1234

echo ""
echo "=========================================="
echo "  ✅ SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "Your LLM is now available at:"
echo ""
echo "  🔗 ${DEVICE_URL}/v1"
echo ""
echo "Use this URL in your Render dashboard:"
echo "  1. Go to AI page"
echo "  2. Click ⚙️ next to provider dropdown"
echo "  3. Enter the URL above"
echo "  4. Click 'Test' to verify"
echo "  5. Click 'Save'"
echo ""
echo "To stop funnel: $TAILSCALE funnel --https=443 off"
echo ""

# Show current status
echo "📊 Current serve status:"
$TAILSCALE serve status 2>/dev/null || echo "   (no status available)"
echo ""
