#!/usr/bin/env python3
"""
FaceDoor — One-click installer and launcher
Works on Windows and macOS/Linux.

Usage:
    python start.py          # from anywhere — paths are resolved automatically
"""

import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
IMPL     = Path(__file__).resolve().parent   # Implementation/
FRONTEND = IMPL / "frontend"
VENV     = IMPL / "venv"
REQS     = IMPL / "requirements.txt"

IS_WIN  = platform.system() == "Windows"
IS_MAC  = platform.system() == "darwin"
VENV_PY = VENV / ("Scripts" / Path("python.exe") if IS_WIN else Path("bin/python3"))

# ── Colour helpers (gracefully disabled on plain Windows terminals) ────────────
_ANSI = not IS_WIN or bool(os.environ.get("WT_SESSION") or os.environ.get("TERM"))

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ANSI else text

ok   = lambda t: _c("32;1", t)
warn = lambda t: _c("33;1", t)
err  = lambda t: _c("31;1", t)
info = lambda t: _c("36", t)
bold = lambda t: _c("1", t)
dim  = lambda t: _c("2", t)


# ── UI helpers ────────────────────────────────────────────────────────────────
def header() -> None:
    print()
    print(bold("═" * 60))
    print(bold("  DoorFace  —  Smart Door Security System"))
    print(bold("═" * 60))
    print()

def step(msg: str) -> None:
    print(f"\n{info('▶')} {bold(msg)}")

def done(msg: str) -> None:
    print(f"  {ok('✓')} {msg}")

def skip(msg: str) -> None:
    print(f"  {dim('–')} {msg}")

def fail(msg: str) -> None:
    print(f"  {err('✗')} {msg}")


# ── Pre-flight checks ─────────────────────────────────────────────────────────
def check_python() -> None:
    step("Checking Python version")
    v = sys.version_info
    label = f"Python {v.major}.{v.minor}.{v.micro}"
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"  {warn(label + '  ← Python 3.10+ required. Download from https://python.org')}")
    else:
        done(label)


def check_node() -> bool:
    step("Checking Node.js / npm")
    if not shutil.which("node"):
        print(f"  {err('Node.js not found.')}")
        print(f"  {warn('  Download and install from: https://nodejs.org  (choose the LTS version)')}")
        print(f"  {warn('  After installing Node.js, re-run this script.')}")
        print(f"  {warn('  The frontend (dashboard) will be skipped for now.')}")
        return False
    try:
        node_v = subprocess.check_output(["node", "--version"], text=True).strip()
        npm_v  = subprocess.check_output(["npm",  "--version"], text=True).strip()
        done(f"Node {node_v}  /  npm v{npm_v}")
        return True
    except Exception:
        done("Node.js found (could not read version)")
        return True


# ── Setup steps ───────────────────────────────────────────────────────────────
def ensure_venv() -> None:
    step("Python virtual environment")
    if VENV_PY.exists():
        skip(f"Already exists at {VENV.name}/")
        return
    print(f"  {info('Creating isolated Python environment ...')}")
    try:
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        done("Virtual environment created")
    except subprocess.CalledProcessError:
        fail("Could not create virtual environment.")
        print(f"  {warn('Make sure Python is installed properly and try again.')}")
        sys.exit(1)


def install_python_deps() -> None:
    step("Python packages  (this may take 5–10 minutes on first run)")
    # Quick probe: if key packages are importable in the venv, skip
    probe = subprocess.run(
        [str(VENV_PY), "-c", "import flask, cv2, mediapipe, ultralytics, requests"],
        capture_output=True,
    )
    if probe.returncode == 0:
        skip("All packages already installed")
        return

    print(f"  {info('Installing packages ... please wait, do not close this window.')}")
    print(f"  {dim('  (Downloading ~500 MB of AI/ML libraries on first run)')}")

    # Upgrade pip silently first
    subprocess.check_call(
        [str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip", "-q"]
    )

    try:
        subprocess.check_call(
            [str(VENV_PY), "-m", "pip", "install", "-r", str(REQS)],
            cwd=str(IMPL),
        )
    except subprocess.CalledProcessError:
        fail("Package installation failed.")
        print(f"  {warn('Check your internet connection and try again.')}")
        print(f"  {warn('If the error mentions a specific package, note it down.')}")
        sys.exit(1)

    done("Python packages installed")

    # Optionally try face_recognition (needs cmake + C++ build tools — optional)
    _try_install_face_recognition()


def _try_install_face_recognition() -> None:
    """Try to install face_recognition (dlib). Optional — system works without it."""
    probe = subprocess.run(
        [str(VENV_PY), "-c", "import face_recognition"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return  # already installed

    print(f"\n  {info('Attempting optional install: face_recognition (better face accuracy) ...')}")
    result = subprocess.run(
        [str(VENV_PY), "-m", "pip", "install", "face_recognition", "-q"],
        capture_output=True,
    )
    if result.returncode == 0:
        done("face_recognition installed  (higher accuracy face matching enabled)")
    else:
        print(f"  {warn('face_recognition could not be installed (needs cmake + C++ build tools).')}")
        print(f"  {dim('  System will use OpenCV for face detection — fully functional.')}")


def install_npm_deps() -> None:
    step("Frontend packages  (npm install)")
    nm = FRONTEND / "node_modules"
    if nm.exists() and (nm / "next").exists():
        skip("Already installed")
        return
    print(f"  {info('Installing frontend packages ... please wait.')}")
    print(f"  {dim('  (Also downloads the AI pose model for fall detection ~25 MB)')}")
    npm_cmd = "npm.cmd" if IS_WIN else "npm"
    try:
        subprocess.check_call([npm_cmd, "install"], cwd=str(FRONTEND))
    except subprocess.CalledProcessError:
        fail("npm install failed.")
        print(f"  {warn('Check your internet connection and try again.')}")
        sys.exit(1)
    done("Frontend packages installed")


# ── Launch helpers ────────────────────────────────────────────────────────────
def _make_env() -> dict:
    env = os.environ.copy()
    env["FLASK_PORT"] = "5001"
    if IS_MAC:
        env.setdefault("OPENCV_VIDEOIO_PRIORITY_AVFOUNDATION", "1000")
    return env


def start_backend() -> subprocess.Popen:
    print(f"\n  {info('Starting backend (Flask API) ...')}")
    log_path = IMPL / "server.log"
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [str(VENV_PY), "main.py"],
        cwd=str(IMPL),
        env=_make_env(),
        stdout=log_file,
        stderr=log_file,
    )
    # Give Flask a moment to start, then check it's actually running
    time.sleep(3)
    if proc.poll() is not None:
        log_file.close()
        fail("Backend failed to start. Check server.log for details:")
        try:
            print(f"\n  {dim(log_path.read_text()[-800:])}")
        except Exception:
            pass
        sys.exit(1)
    done(f"Backend running  →  http://localhost:5001  (logs: server.log)")
    return proc


def start_frontend() -> subprocess.Popen:
    print(f"  {info('Starting dashboard (Next.js) ...')}")
    npm_cmd = "npm.cmd" if IS_WIN else "npm"
    proc = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=str(FRONTEND),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def wait_for_frontend_ready(proc: subprocess.Popen) -> None:
    """Poll until Next.js is serving on :3000 (or timeout after 60s)."""
    import urllib.request
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            fail("Dashboard failed to start.")
            sys.exit(1)
        try:
            urllib.request.urlopen("http://localhost:3000", timeout=2)
            done("Dashboard ready  →  http://localhost:3000")
            return
        except Exception:
            time.sleep(2)
    # Timed out but process is still running — probably just slow
    print(f"  {warn('Dashboard is taking longer than expected.')}")
    print(f"  {warn('Try opening http://localhost:3000 in about 30 seconds.')}")


def open_browser() -> None:
    """Open the dashboard in the default browser."""
    time.sleep(1)
    try:
        webbrowser.open("http://localhost:3000")
        done("Opened http://localhost:3000 in your browser")
    except Exception:
        print(f"  {warn('Could not open browser automatically.')}")
        print(f"  {info('  Please open your browser and go to: http://localhost:3000')}")


def wait_for_processes(procs: list, opened_browser: bool) -> None:
    print()
    print(bold("─" * 60))
    print(ok("  Everything is running!"))
    print()
    print(f"  {bold('Dashboard:')}  http://localhost:3000")
    print(f"  {bold('API:      ')}  http://localhost:5001")
    print()
    if not opened_browser:
        print(f"  {info('Open your browser and go to: http://localhost:3000')}")
        print()
    print(f"  {dim('Press Ctrl+C to stop everything.')}")
    print(bold("─" * 60))
    print()

    def _shutdown(signum=None, frame=None):
        print(warn("\n\n  Shutting down ..."))
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for p in procs:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass
        print(ok("  Stopped cleanly.  Goodbye!\n"))
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    while True:
        for p in procs:
            rc = p.poll()
            if rc is not None:
                print(err(f"\n  A service stopped unexpectedly (exit code {rc})."))
                print(warn("  Check server.log for error details."))
                print(warn("  Press Ctrl+C to exit or wait for restart attempt."))
        time.sleep(2)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    header()

    # Sanity check — make sure we're in the right place
    if not REQS.exists():
        fail(f"Cannot find requirements.txt at: {REQS}")
        fail("Make sure you are running start.py from inside the Implementation/ folder")
        fail("or that the project folder is intact.")
        sys.exit(1)

    # ── Step 1: environment checks ────────────────────────────────────────────
    check_python()
    node_ok = check_node()

    # ── Step 2: install dependencies ─────────────────────────────────────────
    ensure_venv()
    install_python_deps()
    if node_ok:
        install_npm_deps()
    else:
        print(f"\n  {warn('Node.js is required to run the dashboard.')}")
        print(f"  {warn('Backend-only mode is available but the visual dashboard will not work.')}")

    # ── Step 3: ask what to run ───────────────────────────────────────────────
    print()
    print(bold("─" * 60))
    print(bold("  What would you like to start?"))
    print(bold("─" * 60))
    print(f"  {bold('1')}  Backend only   {dim('(API server  →  http://localhost:5001)')}")
    if node_ok:
        print(f"  {bold('2')}  Frontend only  {dim('(Dashboard   →  http://localhost:3000)')}")
        print(f"  {bold('3')}  Both           {ok('← recommended — full system')}")
        print(f"  {bold('4')}  Exit")
        valid = ("1", "2", "3", "4")
    else:
        print(f"  {bold('2')}  Exit")
        valid = ("1", "2")
    print()

    while True:
        choice = input("  Enter your choice: ").strip()
        if choice in valid:
            break
        print(warn(f"  Please enter one of: {', '.join(valid)}"))

    exit_choice = "4" if node_ok else "2"
    if choice == exit_choice:
        print(info("\n  Exiting. Run start.py again whenever you want to start.\n"))
        sys.exit(0)

    # ── Step 4: launch ───────────────────────────────────────────────────────
    print()
    print(bold("─" * 60))
    print(bold("  Starting services ..."))
    print(bold("─" * 60))

    procs = []
    opened_browser = False

    if choice in ("1", "3"):
        procs.append(start_backend())

    if choice in ("2", "3") and node_ok:
        fe_proc = start_frontend()
        procs.append(fe_proc)
        print(f"  {dim('Waiting for dashboard to be ready (up to 60s) ...')}")
        wait_for_frontend_ready(fe_proc)
        open_browser()
        opened_browser = True

    wait_for_processes(procs, opened_browser)


if __name__ == "__main__":
    main()
