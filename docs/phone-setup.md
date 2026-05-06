# Connecting your phone

Your phone reaches PurePrivacy through Tor.  This means you can install the
box on a Raspberry Pi behind a NAT, on a VPS, on a laptop in a different
country — and your phone gets there the same way regardless.

## What you need

- **Element** (the original Element — **recommended for v0.1**).
  - [Element for iOS](https://apps.apple.com/app/element-messenger/id1083446067)
  - [Element for Android](https://play.google.com/store/apps/details?id=im.vector.app)

  > **Use the original Element.**  Element X is the newer sliding-sync
  > client and works for casual use, but in v0.1 its Tor story is
  > rougher: sliding sync over Onion Browser on iOS is flaky, and the
  > cross-signing / device-verification UI you'll need to verify the
  > MCP bot is nested deeper.  Both clients work — but the rest of this
  > guide assumes the original Element.  *Element X notes* are at the
  > bottom for the curious.

- **A Tor proxy on the phone**.
  - Android: [Orbot](https://orbot.app/) (Google Play or F-Droid).
  - iOS: [Onion Browser](https://onionbrowser.com/) — install Onion Browser
    first; it ships an in-app Tor proxy that other apps can use via VPN.
- **The credentials from setup** — either the QR + text printed by
  `pureprivacy init`, or the wizard summary page at `http://127.0.0.1:8088`.
  Both contain the same information.

If you've lost track of the credentials, run `pureprivacy info --secrets`
on the host — it re-displays the admin password, MCP bearer, and
recovery key.

## Walkthrough

1. **Route Element through Tor.**
   - **Android (Orbot):** open Orbot, tap *Start*, then *Settings → Apps*.
     Add **Element** to the list of "Tor-enabled apps."  Orbot will route
     Element's traffic through Tor while leaving the rest of your phone
     untouched.
   - **iOS (Onion Browser):** open Onion Browser, tap *Settings →
     Tor VPN → Start*.  This activates the system-level Tor VPN and routes
     **all** apps through Tor for as long as the VPN is on.  You can leave
     it on permanently, or toggle it just before opening Element.

2. **Verify Tor is working.** In a browser on your phone, open the box's
   `.onion` URL (you'll find it in the wizard's done screen, e.g.
   `http://abc...d.onion`).  You should see Synapse's HTML response:
   "It works! Synapse is running."  If you don't, your Tor proxy isn't
   configured — on iOS, double-check that Onion Browser's *Tor VPN* is on
   (Settings → VPN should show it active); on Android, that Element is in
   Orbot's list of Tor-enabled apps.

3. **Open Element.** Tap *Sign in*, choose *Edit* next to the homeserver,
   and paste the `http://...onion` URL.  Tap *Continue*.

   > Element will warn that the homeserver uses HTTP, not HTTPS.  This is
   > normal for `.onion` services — they don't have publicly-trusted TLS
   > certificates because the onion address itself authenticates the
   > server.  Accept the warning and continue.

4. **Sign in with the credentials from the wizard.** The username is
   `admin` (or whatever you chose); the password is the one you set.
   Element will fetch the homeserver's E2EE configuration and create a
   first device for your phone.

5. **Save your recovery key.** Element prompts you to set up Secure
   Backup.  Do it.  Without the recovery key, encrypted history is
   unrecoverable if you ever reinstall Element.  (This is *Element's*
   recovery key for E2EE history — different from PurePrivacy's recovery
   key for the admin password.  You need both.)

That's it.  You now have an end-to-end encrypted Matrix client on your
phone, talking to a homeserver that is invisible to the public internet.

### Element X notes (alternative — not recommended for v0.1)

Element X is the newer sliding-sync client.  We recommend the original
Element for v0.1 (see the box at the top), but if you want to try
Element X anyway, the flow is the same with two caveats:

- Sliding sync over Tor is sluggish on iOS.  If you see "fetching
  events..." stuck on a fresh login, give it 30–60s and retry.
- Cross-signing/device verification (used for E2EE rooms) is one
  layer deeper in the UI.  In Element X: *Settings → Privacy &
  Security → Sessions → Verify*.  In the original Element: the prompt
  appears on the room banner the first time you join an E2EE room.

## Adding more humans

To bring a friend onto your box, two paths:

- **Same box, different account.**  Two equivalent ways:

  **From the wizard** (recommended for non-technical operators):
  open `http://127.0.0.1:8088`, sign in with your admin password,
  click *People → Add a person*.  Pick a username and password; the
  next page shows a QR you can hand them to sign in.

  **From the host** (good for scripting and SSH-only setups):
  ```bash
  pureprivacy user add alice
  ```
  This creates `@alice:<your-onion>`, generates a strong random password,
  and prints a per-user QR with the homeserver URL.  Hand them the QR +
  password (over a side channel they trust) and they can sign in to
  Element exactly as you did.

  Other user-management commands (mirror the *People* page in the wizard):
  ```bash
  pureprivacy user list                    # who's on the box
  pureprivacy user reset-password alice    # rotate a forgotten password
  pureprivacy user remove alice            # deactivate (data erased)
  pureprivacy user add bob --admin         # second admin
  ```
  Both paths refuse to deactivate the original admin user or the MCP bot.

- **Their own box, federated.** They install PurePrivacy on their own
  hardware.  Open `http://127.0.0.1:8088/pair` (or `pureprivacy pair create`
  on the host) — each box mints a 15-minute pair code; paste each other's
  codes into `/pair/accept` (or `pureprivacy pair accept CODE`).  Synapse
  on each box restarts automatically with the new federation list, and
  the two homeservers can route encrypted rooms over Tor.

## Voice calls

**1:1** voice calls between two phones on the box go through Coturn
over a Tor-tunneled TCP relay.  This works but adds latency — expect
noticeably choppier audio than a direct WebRTC call.

**Group** voice (MatrixRTC / LiveKit) is opt-in:

```bash
pureprivacy up --voice
```

This brings up LiveKit, lk-jwt-service, and a `synapse-fed-proxy` sidecar
that lets lk-jwt validate OpenID tokens against the .onion homeserver.
PurePrivacy remembers the chosen profile, so a later `pureprivacy up`
without flags keeps voice running; pass `--no-voice` to drop it.
See [docs/voice.md](voice.md) for the full picture.

## When something goes wrong

| Symptom                                        | Likely cause                                                            |
|------------------------------------------------|-------------------------------------------------------------------------|
| "Cannot reach the server" in Element           | Tor proxy isn't routing Element.  Re-check Orbot (Android) or Onion Browser's Tor VPN (iOS — make sure the VPN is **on** in iOS Settings → VPN). |
| Element warns about HTTP (not HTTPS)           | Expected — `.onion` services don't have publicly-trusted certificates.  Accept and continue. |
| Login spins forever                            | Synapse is still doing first-run migrations.  Check `pureprivacy status` or `pureprivacy verify`. |
| Messages send but recipients don't see them    | Their device isn't verified — check the key-verification banner.        |
| Voice call connects but cuts out               | Tor latency.  This is a known v0.1 limitation.                          |
