# Safari Push Notifications Setup Guide

## Overview
The Telegram monitoring dashboard now supports push notifications on Safari (both macOS and iOS). When a new message is received, you'll get a notification with the Home Assistant branding and logo.

## Notification Behavior
- **Title**: "Home Assistant"
- **Icon**: Home Assistant logo (HA icon)
- **Body**: Shows count of new automation events
- **On Click**: Does nothing (notification simply closes - no navigation to website)
- **Auto-dismiss**: Closes automatically after 5 seconds

---

## Safari on macOS Setup

### 1. Enable Notifications in macOS
1. Open **System Settings** (or System Preferences on older macOS)
2. Go to **Notifications**
3. Find your browser (**Safari**)
4. Make sure notifications are **enabled**

### 2. Allow Notifications in Safari
1. Open Safari and navigate to the dashboard (e.g., `https://your-dashboard-url.com/messages`)
2. When prompted, click **Allow** to enable notifications
3. If you missed the prompt:
   - Go to **Safari** > **Settings** (or Preferences)
   - Click **Websites** tab
   - Click **Notifications** in the left sidebar
   - Find your dashboard URL and set it to **Allow**

### 3. Add to Home Screen (Optional but Recommended)
For a better app-like experience:
1. In Safari, visit the dashboard
2. Click the **Share** button in the toolbar
3. Select **Add to Dock** or bookmark it
4. The dashboard will now work as a standalone app

**Status**: ✅ Should work immediately once permissions are granted

---

## Safari on iOS/iPadOS Setup

### Important iOS Limitations
Safari on iOS has **significant restrictions** for web push notifications:
- iOS 16.4+ supports Web Push API, but with limitations
- Notifications only work when the site is **added to Home Screen** as a PWA
- Service Workers have limited functionality on iOS
- Background notifications may not work reliably

### 1. Add Dashboard to Home Screen (REQUIRED for iOS)
1. Open **Safari** on your iPhone/iPad
2. Navigate to the dashboard (e.g., `https://your-dashboard-url.com/messages`)
3. Tap the **Share** button (square with arrow pointing up)
4. Scroll down and tap **Add to Home Screen**
5. Give it a name (e.g., "Home Assistant")
6. Tap **Add**

### 2. Enable Notifications on iPhone/iPad
1. Open **Settings** app
2. Scroll down to **Safari** (or find the Home Assistant PWA if added to home screen)
3. Tap **Notifications**
4. Enable **Allow Notifications**
5. Configure:
   - **Lock Screen**: On
   - **Notification Center**: On
   - **Banners**: On
   - **Banner Style**: Temporary or Persistent (your choice)
   - **Sounds**: On (if desired)
   - **Badges**: On (if desired)

### 3. Grant Permission in the App
1. Open the dashboard from your **Home Screen** (not from Safari browser)
2. When prompted, tap **Allow** for notifications
3. If you don't see a prompt:
   - Close and reopen the app
   - Or check Settings > Home Assistant > Notifications

**Status**: ⚠️ **LIMITED** - Works only when added to Home Screen, may not support background notifications reliably

---

## Alternative Solutions for iOS

Since Safari on iOS has limitations, here are alternatives:

### Alternative 1: Use Desktop Safari or Chrome
- If you have a Mac, use Safari or Chrome on macOS instead
- Web notifications work perfectly on desktop browsers
- You can leave the dashboard open in a browser tab

### Alternative 2: Enable "Request Desktop Website" on iOS
1. In Safari on iOS, tap the **aA** button in the address bar
2. Select **Request Desktop Website**
3. This may enable more notification features
4. Note: The interface may not be mobile-optimized

### Alternative 3: Keep Dashboard Tab Open
- Keep the dashboard page open in Safari
- Notifications will appear when you're actively viewing the page
- Background notifications may not work reliably

### Alternative 4: Use Background Refresh (iOS PWA Only)
1. Add the dashboard to Home Screen (see instructions above)
2. Go to **Settings** > **General** > **Background App Refresh**
3. Enable it globally and for the Home Assistant PWA
4. This may help with background notification delivery (not guaranteed)

---

## Troubleshooting

### Notifications Not Appearing

**On macOS:**
1. Check **System Settings** > **Notifications** > **Safari** is enabled
2. Check **Safari** > **Settings** > **Websites** > **Notifications** allows your dashboard
3. Try refreshing the page and allowing notifications again
4. Check browser console for errors (View > Developer > JavaScript Console)

**On iOS:**
1. Verify you added the dashboard to **Home Screen** (required for iOS)
2. Check **Settings** > **Safari** (or app name) > **Notifications** is enabled
3. Open the app from Home Screen, not Safari browser
4. Try removing and re-adding to Home Screen
5. Restart your iPhone/iPad

### Permission Denied or Blocked
1. Go to Safari Settings > Websites > Notifications
2. Remove your dashboard URL from the blocked list
3. Refresh the page and allow notifications when prompted

### Notifications Show but No Sound
1. Check device volume and mute switch
2. On iOS: Settings > Notifications > [App] > Sounds = On
3. On macOS: System Settings > Notifications > Safari > enable sounds

### Icon Not Showing
- The Home Assistant icon should appear automatically
- If not, try clearing Safari cache and refreshing
- Check that `/static/ha-icon.svg` is accessible

---

## Technical Details

### What Was Implemented
1. **PWA Manifest** (`/static/manifest.json`):
   - Defines the app as "Home Assistant"
   - Sets branding colors and icons
   - Enables "Add to Home Screen" on iOS

2. **Safari Meta Tags** (in `base_v6.html`):
   - `apple-mobile-web-app-capable`: Enables fullscreen mode on iOS
   - `apple-mobile-web-app-title`: Sets app name to "Home Assistant"
   - `apple-touch-icon`: Sets Home Assistant icon for home screen
   - `theme-color`: Sets browser theme color

3. **Enhanced Notification Logic** (in `messages_v6.html`):
   - Detects Safari and iOS browsers
   - Handles permission requests properly for Safari
   - Disables unsupported features (like vibration on iOS)
   - Better error handling for Safari quirks

4. **Service Worker Updates** (`/static/sw.js`):
   - Improved cache management
   - Better notification handling
   - Compatible with Safari's limited service worker support

### Browser Support
| Browser | macOS | iOS/iPadOS | Notes |
|---------|-------|------------|-------|
| Safari | ✅ Full support | ⚠️ Limited | iOS requires PWA (Home Screen) |
| Chrome | ✅ Full support | ✅ Full support | Best experience |
| Firefox | ✅ Full support | ⚠️ Limited | iOS uses Safari engine |
| Edge | ✅ Full support | ✅ Full support | Chromium-based |

### Known Limitations
1. **iOS Web Push Restrictions**:
   - Only works when added to Home Screen as PWA
   - Background notifications unreliable
   - Service Workers have limited capabilities
   - Cannot customize notification sounds

2. **Safari-Specific Quirks**:
   - Notification permission must be requested from user interaction
   - Some notification options (vibrate) not supported
   - May auto-dismiss notifications sooner than other browsers

3. **No Navigation on Click**:
   - By design, clicking notifications does nothing
   - This is to keep the monitoring dashboard "secret" (per original request)
   - Notifications only close when clicked

---

## How It Works

1. **Message Received**:
   - Backend (monitor.py) detects new Telegram message
   - Message saved to database
   - Push notification triggered

2. **Notification Displayed**:
   - Frontend checks for new messages on page load/refresh
   - If new messages found, shows notification with HA branding
   - Notification auto-closes after 5 seconds

3. **User Interaction**:
   - If user clicks notification: it closes (no navigation)
   - If user ignores: auto-closes after 5 seconds

---

## FAQ

**Q: Do I need to keep the dashboard open in Safari?**
A: On macOS - No, notifications work in background. On iOS - Yes, or add to Home Screen.

**Q: Will notifications work when my phone is locked?**
A: On iOS - Only if added to Home Screen and background refresh enabled. On macOS - Yes.

**Q: Can I change the notification sound?**
A: Not through the web app. Use your device's notification settings to change Safari's notification sound.

**Q: Why doesn't clicking the notification open the dashboard?**
A: By design - the notification does nothing when clicked to keep the monitoring discreet.

**Q: Do I need to enable anything special on my phone?**
A: On iOS: Add to Home Screen + enable Notifications in Settings. On macOS: Just allow notifications in Safari.

**Q: Can I use this on Android?**
A: Yes! Android has full support for web push notifications in Chrome, Firefox, and Edge. No special setup needed.

---

## Testing Your Setup

1. Open the dashboard in Safari
2. Send a test message to the monitored Telegram account
3. Refresh the dashboard page
4. You should see a notification with "Home Assistant" title and HA logo
5. Click the notification - it should close without opening anything

If notifications don't appear, follow the troubleshooting steps above.

---

## Support

If you continue to have issues:
1. Check browser console for errors (Safari > Develop > Show JavaScript Console)
2. Verify notification permissions in system settings
3. Try a different browser to isolate Safari-specific issues
4. On iOS, ensure you're using iOS 16.4 or later for best compatibility
