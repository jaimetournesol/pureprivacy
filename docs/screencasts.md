# Screencasts

Four short captures of the v0.1 user journey, captured against a fresh
appliance running the
[friendly-home-page UI work](#).  Watch them in order — the four clips
form one continuous setup, half on the laptop's web wizard and half on
the new user's phone.

All metadata has been stripped from the source files (no creation
timestamps, no GPS, no device identifiers, no encoder fingerprint).

## 1. Admin's first login on the web wizard

The operator opens `http://127.0.0.1:8088` for the first time after
running `pureprivacy init`.  The login screen surfaces the
auto-generated admin password directly — a one-time helper gated by
the `.first-login-done` sentinel so it disappears after the first
successful sign-in.  The reveal counter sits at 1 (legitimate first
view).

<video controls width="700" preload="metadata">
  <source src="media/01-admin-first-login.mp4" type="video/mp4">
  <a href="media/01-admin-first-login.mp4">Download 01-admin-first-login.mp4</a>
</video>

What to look for:
- "First-time sign in" panel with the auto-password
- 📊 view counter showing **1** (Looks normal)
- After sign-in: the safety-card home page with the four numbered steps

## 2. Inviting a friend from the wizard

From the home page the operator navigates to **Friends** (the renamed
`/people` route) and creates an account for Bob.  The share-with-them
page that drops out the other side is the same safety-card layout as
the home page — same four numbered steps, with Bob's username and
freshly-minted password swapped in.

<video controls width="700" preload="metadata">
  <source src="media/02-invite-a-friend.mp4" type="video/mp4">
  <a href="media/02-invite-a-friend.mp4">Download 02-invite-a-friend.mp4</a>
</video>

What to look for:
- The same four-step Element + Orbot install flow as on the home page
- One-time view warning on the password (`pureprivacy user reset-password`
  is the only path to recover if the page is closed)
- Per-field "📷 Show as QR" toggles so the new user can scan-to-copy
  with their phone camera

## 3. Admin's first phone setup

Phone-side capture of the operator following Steps 1-4 on the home
page: install **Element** + **Orbot** from the Play/App Store QRs,
start Orbot's VPN, paste the homeserver address into Element, **Sign
in** (not Create Account), enter the username and password.  Status
panel on the laptop side flips to "Phone connected" within ~5
seconds of a successful login.

<video controls width="540" preload="metadata">
  <source src="media/03-admin-first-phone-setup.mp4" type="video/mp4">
  <a href="media/03-admin-first-phone-setup.mp4">Download 03-admin-first-phone-setup.mp4</a>
</video>

What to look for:
- Camera scan of the install QRs deep-links straight into each store
- Orbot VPN prompt + "Connected to the Tor network" status
- The "Sign in / Create account" choice in Element — must pick Sign in
- HTTP-not-HTTPS warning Element shows for `.onion` — accept

## 4. Friend's first contact from their own phone

Bob receives the share page from Step 2 and goes through the same
phone-side flow on their own device.  This time the credentials are
Bob's, the bot's auto-accept means a one-line first message from
Bob lands in the room before any humans had to verify anything else.

<video controls width="540" preload="metadata">
  <source src="media/04-friend-first-contact.mp4" type="video/mp4">
  <a href="media/04-friend-first-contact.mp4">Download 04-friend-first-contact.mp4</a>
</video>

What to look for:
- Same install / Orbot dance as the admin in clip 3 — the share page
  is intentionally identical to the home page so there's no second
  flow to learn
- First message from Bob arriving in the room
- (Out of frame: the laptop's status panel ticking up to two devices)

## Provenance

These captures were recorded on a fresh `pureprivacy init --voice`
box running the changes from the `friendly-home-page` branch.  Source
files were re-encoded through ffmpeg with `-map_metadata -1
-map_chapters -1 -fflags +bitexact` to remove:

- Original creation timestamps
- Phone GPS coordinates (the iOS / Android default)
- Device make / model / OS version
- The original recording software's encoder fingerprint
- Any chapter / title / description fields

The re-encode used libx264 with default colour space, so the visible
content is byte-for-byte the same the operator and recipient saw, just
without the silent fingerprinting fields.

## Notes

- Voice / video calls are *not* in these captures.  1:1 calls over Tor
  hit a WebRTC limitation in v0.1 (Element requests UDP TURN
  allocations which Tor cannot carry); the LiveKit-backed Element Call
  group path is closer but depends on Element's tolerance for the
  appliance's self-signed onion cert.  Track [voice work in
  v0.2](v0.1.x-plan.md#) for the planned fix.
- The "Show as QR" toggles in clip 2 are demonstrated more thoroughly
  in clip 3 (phone scanning them).
