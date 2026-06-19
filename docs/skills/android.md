# Android Skill

Build, test, and control Android apps on the emulator — supports Expo, bare React Native, and raw Gradle projects.

**File:** `skills/android.py`

---

## Tools

### android

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | See actions below |
| `project` | string | no | Project name or path (default: `jarvis-mobile`) |
| `avd` | string | no | AVD name (default: `Pixel_6`) |
| `variant` | string | no | `debug` or `release` (default: `debug`) |
| `task` | string | no | Gradle task or raw adb args |
| `framework` | string | no | `auto`, `jest`, `detox`, `maestro` (default: auto-detect) |
| `package` | string | no | Android package ID for launch (default: `com.porokka.jarvismobile`) |
| `port` | integer | no | Metro bundler port (default: 8081) |

---

## Actions

| Action | Description |
|--------|-------------|
| `build` | Build via `npx expo run:android` (Expo) or `./gradlew assembleDebug` (bare) |
| `gradle` | Run any Gradle task — specify with `task` param |
| `test` | Run tests — auto-detects Jest / Detox / Maestro |
| `run` / `deploy` | Full pipeline: start emulator → build → install APK → launch app → screenshot |
| `install` | Install built APK onto running emulator |
| `launch` | Launch the installed app |
| `start_emulator` | Start an AVD (default: Pixel_6) |
| `stop_emulator` | Kill running emulator |
| `screenshot` | Capture emulator screen to `staging/screenshots/android_*.png` |
| `emulator_status` | Check which emulators are currently running |
| `list_avds` | List all installed AVDs |
| `adb` | Run a raw `adb` command — specify command in `task` param |

---

## Examples

```
"Build the jarvis-mobile android app"
"Run jarvis mobile on android emulator"
"Take a screenshot of the emulator"
"Run android tests"
"Start the Pixel_6 emulator"
"Gradle bundleRelease for jarvis-mobile"
"adb shell dumpsys activity"
```

---

## Project Detection

| Check | Detected As |
|-------|-------------|
| `app.json` or `app.config.js` exists | Expo project → `npx expo run:android` |
| Only `android/gradlew` | Bare React Native → `./gradlew assembleDebug` |

---

## Test Framework Detection

| Check | Framework |
|-------|-----------|
| `.detoxrc.js` or `.detoxrc.json` or `e2e/` folder | Detox |
| `maestro/` folder or `.yaml` flow files | Maestro |
| Fallback | Jest |

---

## Config

`ANDROID_HOME` is read from environment or defaults to `~/AppData/Local/Android/Sdk` (Windows).

Add to `.env` in jarvis-os:
```bash
ANDROID_HOME=C:/Users/yourname/AppData/Local/Android/Sdk
JAVA_HOME=C:/Program Files/Microsoft/jdk-21
```

Screenshots saved to `staging/screenshots/android_<timestamp>.png`.
