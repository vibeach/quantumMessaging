# Tailscale Funnel Setup for Local LLM

This guide explains how to expose your local LM Studio server to the internet using Tailscale Funnel, allowing your Render-hosted dashboard to use your local LLM.

## Overview

```
[Render Dashboard] → [Internet] → [Tailscale Funnel] → [Your Mac] → [LM Studio :1234]
```

Your local LLM becomes accessible via a public HTTPS URL like:
```
https://your-machine.tailnet.ts.net/v1
```

---

## Prerequisites

1. **Tailscale installed** on your Mac ([download](https://tailscale.com/download))
2. **Tailscale account** and logged in
3. **LM Studio** running with server enabled on port 1234

---

## One-Time Setup: Enable Funnel in Tailscale Admin

1. Go to: **https://login.tailscale.com/admin/settings/features**

2. Enable these two features:
   - ✅ **HTTPS certificates** - Allows provisioning TLS certificates
   - ✅ **Funnel** - Allows exposing services to the internet

3. Click Save/Apply if prompted

---

## Start Funnel (Run Each Time)

### Option 1: Use the Script

```bash
cd ~/workspace/vibe\ coding/telegram
./scripts/tailscale-funnel-setup.sh
```

The script will:
- Check Tailscale is connected
- Check LM Studio is running
- Set up the funnel
- Display your public URL

### Option 2: Manual Commands

```bash
# Set Tailscale path (macOS with app)
TAILSCALE="/Applications/Tailscale.app/Contents/MacOS/Tailscale"

# Start funnel (simple one-liner)
$TAILSCALE funnel --bg http://localhost:1234

# Check status
$TAILSCALE serve status
```

---

## Configure Render Dashboard

1. Go to your Render dashboard → **AI page**

2. Click the **⚙️ button** next to the provider dropdown (top right)

3. In the "Tailscale LLM URL" field, enter your URL:
   ```
   https://alessandros-macbook-pro-1.tailb97259.ts.net/v1
   ```

4. Click **Test** to verify connection
   - Should show: "✓ Connected! Model: [your model name]"

5. Click **Save**

6. Select **"Local LLM (Tailscale)"** from the provider dropdown

---

## Your Current Setup

| Setting | Value |
|---------|-------|
| Public URL | `https://alessandros-macbook-pro-1.tailb97259.ts.net/v1` |
| Local Port | 1234 |
| Model | Qwen2.5-7B-Instruct-jailbreak-ES.Q8_0.gguf |

---

## Commands Reference

| Action | Command |
|--------|---------|
| **Start funnel** | `./scripts/tailscale-funnel-setup.sh` |
| **Stop funnel** | `/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel --https=443 off` |
| **Check status** | `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status` |
| **Reset config** | `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve reset` |

---

## Troubleshooting

### Funnel commands timeout
- Make sure Tailscale app is running (check menu bar icon)
- Try: `killall Tailscale && open /Applications/Tailscale.app`

### 502 Bad Gateway
- LM Studio might not be running
- Check: `curl http://localhost:1234/v1/models`
- Reset funnel: `$TAILSCALE serve reset && $TAILSCALE funnel --bg http://localhost:1234`

### "Funnel not enabled" error
- Go to https://login.tailscale.com/admin/settings/features
- Enable both "HTTPS certificates" and "Funnel"

### Can't find ⚙️ button in dashboard
- Hard refresh the page (Cmd+Shift+R / Ctrl+Shift+R)
- Clear browser cache
- Check Render deployment completed

### Connection refused on Render
- Funnel might have stopped (Mac went to sleep, etc.)
- Re-run: `./scripts/tailscale-funnel-setup.sh`

---

## Notes

- Funnel stops when your Mac sleeps or restarts
- Run the setup script again after reboot
- The URL stays the same as long as you use the same Tailscale account
- Free Tailscale accounts support Funnel
