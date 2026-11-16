# Making the APK

The site is already an installable app. PWABuilder wraps it in an Android shell — a Trusted Web
Activity, which is Chrome without the browser around it, so the microphone works with no native code.

Nothing here needs Android Studio, and you do not have to be on Windows.

## 1. Generate it

1. Go to **[pwabuilder.com](https://www.pwabuilder.com)**
2. Paste **`https://sadih.onrender.com`** and press Start
3. It scores the manifest, the service worker and the icons. Everything it needs is already there.
4. **Package for stores → Android → Generate**
5. Leave the defaults, except:
   - **App name**: `صادِح`
   - **Package ID**: `ai.sad7.sadih` (this can never change once you publish — pick it now)
   - **Signing key**: *Create new*, and **download the zip** it gives you

The zip contains:

| file | what it is |
|---|---|
| `app-release-signed.apk` | the file you send people |
| `app-release-bundle.aab` | only for Google Play, ignore for now |
| `assetlinks.json` | **do not skip this — see below** |
| `signing.keystore` + passwords | **back this up somewhere safe** |

**The keystore is not replaceable.** Lose it and you can never ship an update to the same app;
everyone would have to uninstall and reinstall. Put it somewhere the team can find it, not just on
one laptop.

## 2. Remove the address bar

Without this step the app opens with Chrome's URL bar across the top, which looks like a website in a
frame rather than an app.

1. Take `assetlinks.json` out of the zip
2. Save it as **`stage1/web/assetlinks.json`**
3. Commit and push — Render redeploys on its own
4. Check it: `https://sadih.onrender.com/.well-known/assetlinks.json` should return the file, not a 404

The route already exists and returns a clear 404 until you add the file.

Android verifies this the first time the app runs, so install the APK **after** the file is live. If
you installed it first, uninstall and reinstall.

## 3. Install it

Send the `.apk` by WhatsApp, Drive, or a USB cable. On the phone:

- Android will warn about installing from an unknown source — allow it for whatever app is doing the
  installing. This warning is normal for an APK that did not come from Play.
- Open it. The passcode screen comes first, then the mic.

## What the app can and cannot do

**It can**: run full screen with its own icon, use the microphone, and show an offline message when
there is no network.

**It cannot float over other apps.** That needs a real native app with Android's overlay permission,
and on iPhone it is not possible at all. The floating button in the demo works because we control
that whole fake screen. If floating over WhatsApp ever becomes a requirement, that is a native
Android build, not a wrapper around this.

## iPhone

There is no APK for iPhone, and Apple does not allow this kind of wrapper in the App Store. On an
iPhone: open the site in Safari → Share → **Add to Home Screen**. You get the icon and full screen,
which is as close as iOS allows without a native build.

## When you change the app

The APK points at the live site, so a push to `main` updates what everyone sees. You only rebuild the
APK if the icon, the name or the package ID changes.
