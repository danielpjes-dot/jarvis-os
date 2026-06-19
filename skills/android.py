"""
JARVIS Skill — Android app build and test utility.

Supports:
- Expo / React Native projects (npx expo run:android)
- Raw Gradle builds (./gradlew assembleDebug)
- Android emulator control (start, stop, screenshot, list)
- APK install / launch on emulator
- Jest / Detox / Maestro test runs
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

SKILL_NAME = "android"
SKILL_DESCRIPTION = "Build, install, test, and control Android apps via emulator"
SKILL_VERSION = "1.0.0"
SKILL_CATEGORY = "mobile"
SKILL_TAGS = ["android", "expo", "react-native", "gradle", "emulator", "mobile"]

SKILL_META = {
    "name": SKILL_NAME,
    "description": SKILL_DESCRIPTION,
    "entrypoint": "exec_android",
    "route": "tools",
    "intent_aliases": ["android build", "android test", "run android", "expo android", "emulator"],
    "keywords": ["android", "emulator", "gradle", "expo", "react native", "apk", "avd"],
    "direct_match": ["android build", "android test", "start emulator"],
    "network_access": False,
    "writes_files": False,
    "response_style": {
        "default": "structured_status_ui",
        "avoid_raw_dump": False,
    },
}

# ── Config ────────────────────────────────────────────────────────────────────

PROJECTS: Dict[str, str] = {
    "jarvis-mobile":    "E:/coding/jarvis-mobile",
    "jarvis_mobile":    "E:/coding/jarvis-mobile",
    "mobile":           "E:/coding/jarvis-mobile",
}

DEFAULT_EMULATOR  = "Pixel_6"
DEFAULT_AVD_PORT  = 5554
METRO_PORT        = 8081
METRO_PORT_ALT    = 8082
SCREENSHOT_DIR    = Path("E:/coding/jarvis-os/staging/screenshots")

_ANDROID_HOME = (
    os.environ.get("ANDROID_HOME")
    or os.environ.get("ANDROID_SDK_ROOT")
    or str(Path.home() / "AppData/Local/Android/Sdk")
)

_EMULATOR_BIN = str(Path(_ANDROID_HOME) / "emulator" / "emulator.exe")
_ADB_BIN      = str(Path(_ANDROID_HOME) / "platform-tools" / "adb.exe")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: str, cwd: str = None, timeout: int = 300, env_extra: dict = None) -> tuple[bool, str]:
    env = os.environ.copy()
    env["ANDROID_HOME"] = _ANDROID_HOME
    env["JAVA_HOME"]    = os.environ.get("JAVA_HOME", "")
    if env_extra:
        env.update(env_extra)

    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()[-3000:]  # cap output
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def _resolve_project(project: str) -> Optional[str]:
    if not project:
        return PROJECTS.get("jarvis-mobile")
    key = project.lower().replace(" ", "-").replace("_", "-")
    if key in PROJECTS:
        return PROJECTS[key]
    p = Path(project)
    if p.exists():
        return str(p)
    # Try E:/coding/<project>
    guess = Path("E:/coding") / project
    if guess.exists():
        return str(guess)
    return None


def _is_expo(project_path: str) -> bool:
    return (Path(project_path) / "app.json").exists() or \
           (Path(project_path) / "app.config.js").exists()


def _adb(args: str, timeout: int = 30) -> tuple[bool, str]:
    return _run(f'"{_ADB_BIN}" {args}', timeout=timeout)


def _status_result(title: str, msg: str, ok: bool, data: dict = None) -> dict:
    return {
        "ok": ok,
        "speech": {"text": msg, "priority": "normal"},
        "ui": {
            "placement": "right-side-hud",
            "format": "status",
            "title": title,
            "summary": msg,
            "ttl_seconds": 120,
        },
        "data": data or {"plain": msg},
    }


# ── Actions ───────────────────────────────────────────────────────────────────

def _emulator_list() -> tuple[bool, str]:
    ok, out = _run(f'"{_EMULATOR_BIN}" -list-avds', timeout=15)
    return ok, out


def _emulator_running() -> list[str]:
    ok, out = _adb("devices")
    devices = []
    for line in out.splitlines():
        if "emulator-" in line and "device" in line:
            devices.append(line.split()[0])
    return devices


def _emulator_start(avd: str = DEFAULT_EMULATOR) -> tuple[bool, str]:
    running = _emulator_running()
    if running:
        return True, f"Emulator already running: {running[0]}"
    cmd = f'start "" "{_EMULATOR_BIN}" -avd {avd} -no-snapshot-save'
    ok, out = _run(cmd, timeout=15)
    # Wait up to 30s for it to come online
    for _ in range(15):
        time.sleep(2)
        if _emulator_running():
            return True, f"Emulator {avd} online."
    return False, f"Emulator {avd} started but not yet online. Check Android Studio."


def _emulator_stop() -> tuple[bool, str]:
    ok, out = _adb("emu kill")
    return ok, "Emulator stopped." if ok else out


def _screenshot(avd_serial: str = None) -> tuple[bool, str]:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    local = SCREENSHOT_DIR / f"android_{ts}.png"
    serial = f"-s {avd_serial}" if avd_serial else ""
    ok, out = _adb(f'{serial} exec-out screencap -p > "{local}"')
    if ok and local.exists() and local.stat().st_size > 1000:
        return True, str(local)
    return False, out or "Screenshot failed — emulator may not be fully booted"


def _build_expo(project_path: str, variant: str = "debug", port: int = METRO_PORT) -> tuple[bool, str]:
    env = {"EXPO_NO_DOTENV": "1"}
    # Try preferred port, fallback handled by expo itself
    cmd = f'npx expo run:android --variant {variant} --port {port} --no-bundler'
    return _run(cmd, cwd=project_path, timeout=600, env_extra=env)


def _build_gradle(project_path: str, task: str = "assembleDebug") -> tuple[bool, str]:
    android_dir = str(Path(project_path) / "android")
    gradlew = "gradlew.bat" if os.name == "nt" else "./gradlew"
    return _run(f'{gradlew} {task} --daemon', cwd=android_dir, timeout=600)


def _install_apk(project_path: str) -> tuple[bool, str]:
    apk_paths = list(Path(project_path).glob("android/app/build/outputs/apk/debug/*.apk"))
    if not apk_paths:
        return False, "No debug APK found — run build first"
    apk = str(apk_paths[0])
    return _adb(f'install -r "{apk}"', timeout=60)


def _launch_app(package: str = "com.porokka.jarvismobile") -> tuple[bool, str]:
    return _adb(
        f'shell monkey -p {package} -c android.intent.category.LAUNCHER 1',
        timeout=15,
    )


def _run_tests(project_path: str, framework: str = "auto") -> tuple[bool, str]:
    p = Path(project_path)

    # Auto-detect test framework
    if framework == "auto":
        if (p / "e2e").exists() or (p / ".detoxrc.js").exists() or (p / ".detoxrc.json").exists():
            framework = "detox"
        elif (p / "maestro").exists() or list(p.glob("**/*.yaml")):
            framework = "maestro"
        else:
            framework = "jest"

    if framework == "jest":
        return _run("npx jest --passWithNoTests --forceExit", cwd=project_path, timeout=120)
    elif framework == "detox":
        return _run("npx detox test -c android.emu.debug", cwd=project_path, timeout=300)
    elif framework == "maestro":
        flow_dir = str(p / "maestro")
        return _run(f"maestro test {flow_dir}", cwd=project_path, timeout=300)
    else:
        return False, f"Unknown test framework: {framework}"


# ── Main executor ─────────────────────────────────────────────────────────────

def exec_android(
    action: str,
    project: str = "jarvis-mobile",
    avd: str = DEFAULT_EMULATOR,
    variant: str = "debug",
    task: str = "assembleDebug",
    framework: str = "auto",
    package: str = "com.porokka.jarvismobile",
    port: int = METRO_PORT,
) -> Dict[str, Any]:
    action = (action or "").strip().lower()

    # ── Emulator actions (no project needed) ─────────────────────────────────
    if action == "list_avds":
        ok, out = _emulator_list()
        return _status_result("AVD List", out if ok else "Could not list AVDs", ok, {"avds": out})

    if action == "emulator_status":
        devices = _emulator_running()
        msg = f"Running: {', '.join(devices)}" if devices else "No emulator running"
        return _status_result("Emulator Status", msg, bool(devices), {"devices": devices})

    if action == "start_emulator":
        ok, msg = _emulator_start(avd)
        return _status_result("Start Emulator", msg, ok)

    if action == "stop_emulator":
        ok, msg = _emulator_stop()
        return _status_result("Stop Emulator", msg, ok)

    if action == "screenshot":
        devices = _emulator_running()
        serial = devices[0] if devices else None
        ok, path_or_err = _screenshot(serial)
        return _status_result(
            "Screenshot",
            f"Saved: {path_or_err}" if ok else path_or_err,
            ok,
            {"path": path_or_err} if ok else {},
        )

    if action == "adb":
        # Pass-through raw adb command via `task` param
        ok, out = _adb(task)
        return _status_result("ADB", out[:300], ok, {"output": out})

    # ── Project actions ───────────────────────────────────────────────────────
    project_path = _resolve_project(project)
    if not project_path:
        return _status_result("Android", f"Project not found: {project}", False)

    if action == "build":
        if _is_expo(project_path):
            ok, out = _build_expo(project_path, variant, port)
        else:
            ok, out = _build_gradle(project_path, task)
        tail = out[-600:] if out else ""
        return _status_result(
            "Android Build",
            f"Build {'succeeded' if ok else 'failed'} — {project}",
            ok,
            {"output": tail},
        )

    if action == "gradle":
        ok, out = _build_gradle(project_path, task)
        tail = out[-600:] if out else ""
        return _status_result("Gradle", f"Task {task}: {'OK' if ok else 'FAILED'}", ok, {"output": tail})

    if action == "install":
        ok, out = _install_apk(project_path)
        return _status_result("Install APK", out[:200], ok)

    if action == "launch":
        ok, out = _launch_app(package)
        return _status_result("Launch App", out[:200], ok)

    if action == "test":
        ok, out = _run_tests(project_path, framework)
        tail = out[-800:] if out else ""
        return _status_result(
            "Android Tests",
            f"Tests {'passed' if ok else 'failed'} ({framework})",
            ok,
            {"output": tail, "framework": framework},
        )

    if action in ("deploy", "run"):
        # Full pipeline: build → install → launch → screenshot
        steps = []

        # 1. Ensure emulator is running
        devices = _emulator_running()
        if not devices:
            ok, msg = _emulator_start(avd)
            steps.append(f"emulator: {'OK' if ok else 'FAILED — ' + msg}")
            if not ok:
                return _status_result("Deploy", "\n".join(steps), False, {"steps": steps})
            time.sleep(5)  # brief settle

        # 2. Build
        if _is_expo(project_path):
            ok, out = _build_expo(project_path, variant, port)
        else:
            ok, out = _build_gradle(project_path, task)
        steps.append(f"build: {'OK' if ok else 'FAILED'}")
        if not ok:
            return _status_result("Deploy", "\n".join(steps), False, {"steps": steps, "output": out[-600:]})

        # 3. Install
        ok, out = _install_apk(project_path)
        steps.append(f"install: {'OK' if ok else 'FAILED — ' + out[:80]}")

        # 4. Launch
        ok, out = _launch_app(package)
        steps.append(f"launch: {'OK' if ok else 'FAILED'}")

        # 5. Screenshot
        time.sleep(3)
        devices = _emulator_running()
        ok_ss, ss_path = _screenshot(devices[0] if devices else None)
        steps.append(f"screenshot: {ss_path if ok_ss else 'FAILED'}")

        all_ok = all("FAILED" not in s for s in steps)
        return _status_result(
            "Deploy to Emulator",
            f"Deploy {'complete' if all_ok else 'partial'} — {project}",
            all_ok,
            {"steps": steps, "screenshot": ss_path if ok_ss else None},
        )

    return _status_result(
        "Android",
        "Unknown action. Use: build, gradle, test, run, deploy, install, launch, "
        "start_emulator, stop_emulator, screenshot, emulator_status, list_avds, adb",
        False,
    )


# ── Tool definition ───────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "android",
            "description": (
                "Build, test, and control Android apps on an emulator. "
                "Actions: build (expo/gradle), test (jest/detox/maestro), run/deploy (full pipeline), "
                "install (APK), launch (app), start_emulator, stop_emulator, screenshot, "
                "emulator_status, list_avds, gradle (raw task), adb (raw command)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "build", "gradle", "test", "run", "deploy",
                            "install", "launch",
                            "start_emulator", "stop_emulator", "screenshot",
                            "emulator_status", "list_avds", "adb",
                        ],
                        "description": "Action to perform.",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project name (e.g. jarvis-mobile) or full path. Default: jarvis-mobile.",
                    },
                    "avd": {
                        "type": "string",
                        "description": "Android Virtual Device name. Default: Pixel_6.",
                    },
                    "variant": {
                        "type": "string",
                        "enum": ["debug", "release"],
                        "description": "Build variant. Default: debug.",
                    },
                    "task": {
                        "type": "string",
                        "description": "Gradle task (e.g. assembleDebug, bundleRelease) or raw adb args.",
                    },
                    "framework": {
                        "type": "string",
                        "enum": ["auto", "jest", "detox", "maestro"],
                        "description": "Test framework. Default: auto-detect.",
                    },
                    "package": {
                        "type": "string",
                        "description": "Android package ID for launch action. Default: com.porokka.jarvismobile.",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Metro bundler port. Default: 8081.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {"android": exec_android}

KEYWORDS = {
    "android": [
        "android", "emulator", "apk", "gradle", "expo android",
        "react native", "build android", "test android", "run android",
        "pixel", "avd",
    ],
}

SKILL_EXAMPLES = [
    {"command": "build android jarvis-mobile", "tool": "android", "args": {"action": "build"}},
    {"command": "run android app on emulator", "tool": "android", "args": {"action": "deploy"}},
    {"command": "take screenshot of emulator", "tool": "android", "args": {"action": "screenshot"}},
    {"command": "start Pixel_6 emulator", "tool": "android", "args": {"action": "start_emulator"}},
    {"command": "run android tests", "tool": "android", "args": {"action": "test"}},
]
