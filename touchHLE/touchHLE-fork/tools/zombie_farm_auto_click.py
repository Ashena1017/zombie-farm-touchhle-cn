"""Launch touchHLE and click the center of its game window.

Windows-only helper for local Zombie Farm 2 regression runs. It intentionally
uses only Python's standard library so it works in a fresh checkout.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import subprocess
import sys
import time
from pathlib import Path


user32 = ctypes.windll.user32

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

SW_RESTORE = 9
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_F11 = 0x7A


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


def window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def process_id_for_window(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def find_window_for_process(pid: int, title_hint: str, timeout: float) -> int:
    title_hint = title_hint.lower()
    deadline = time.time() + timeout

    while time.time() < deadline:
        matches: list[int] = []

        @EnumWindowsProc
        def enum_window(hwnd: int, _: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            if process_id_for_window(hwnd) != pid:
                return True
            title = window_text(hwnd)
            if title_hint and title_hint not in title.lower():
                return True
            matches.append(hwnd)
            return True

        user32.EnumWindows(enum_window, 0)
        if matches:
            return matches[0]
        time.sleep(0.1)

    raise RuntimeError(f"could not find window for pid {pid}")


def client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetClientRect failed")

    top_left = POINT(rect.left, rect.top)
    bottom_right = POINT(rect.right, rect.bottom)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        raise RuntimeError("ClientToScreen(top_left) failed")
    if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
        raise RuntimeError("ClientToScreen(bottom_right) failed")

    return (
        int(top_left.x),
        int(top_left.y),
        int(bottom_right.x - top_left.x),
        int(bottom_right.y - top_left.y),
    )


def send_click(screen_x: int, screen_y: int) -> None:
    screen_w = max(1, user32.GetSystemMetrics(0) - 1)
    screen_h = max(1, user32.GetSystemMetrics(1) - 1)
    abs_x = int(screen_x * 65535 / screen_w)
    abs_y = int(screen_y * 65535 / screen_h)

    events = (
        INPUT(
            INPUT_MOUSE,
            INPUT_UNION(
                mi=MOUSEINPUT(
                    abs_x,
                    abs_y,
                    0,
                    MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
                    0,
                    None,
                )
            ),
        ),
        INPUT(
            INPUT_MOUSE,
            INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)),
        ),
        INPUT(
            INPUT_MOUSE,
            INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)),
        ),
    )
    sent = user32.SendInput(len(events), ctypes.byref((INPUT * len(events))(*events)), ctypes.sizeof(INPUT))
    if sent != len(events):
        raise RuntimeError(f"SendInput sent {sent}/{len(events)} events")


def send_key(vk: int) -> None:
    events = (
        INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(vk, 0, 0, 0, None))),
        INPUT(
            INPUT_KEYBOARD,
            INPUT_UNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)),
        ),
    )
    sent = user32.SendInput(
        len(events), ctypes.byref((INPUT * len(events))(*events)), ctypes.sizeof(INPUT)
    )
    if sent != len(events):
        raise RuntimeError(f"SendInput sent {sent}/{len(events)} keyboard events")


def dump_inspector(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    send_key(VK_F11)


def click_window_center(hwnd: int, ratio_x: float, ratio_y: float) -> tuple[int, int]:
    left, top, width, height = client_rect_on_screen(hwnd)
    x = left + int(width * ratio_x)
    y = top + int(height * ratio_y)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    send_click(x, y)
    return x, y


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ipa",
        nargs="?",
        default=r"X:\ios_game\The Zombie Farm Archive\Zombie Farm 2\Zombie_Farm_2_2.25.ipa",
        help="IPA path.",
    )
    parser.add_argument("--exe", default=r"target\release\touchHLE.exe", help="touchHLE executable.")
    parser.add_argument("--device-family", default="ipad", help="touchHLE --device-family value.")
    parser.add_argument("--title", default="", help="Optional window title substring.")
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    parser.add_argument("--initial-delay", type=float, default=3.0, help="Delay after the window appears.")
    parser.add_argument(
        "--wait-log-pattern",
        default="",
        help="Wait until the launch log contains this text before the initial delay.",
    )
    parser.add_argument(
        "--wait-log-timeout",
        type=float,
        default=30.0,
        help="Maximum seconds to wait for --wait-log-pattern.",
    )
    parser.add_argument("--clicks", type=int, default=1, help="Number of center clicks.")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between clicks.")
    parser.add_argument("--center-ratio-x", type=float, default=0.5)
    parser.add_argument("--center-ratio-y", type=float, default=0.5)
    parser.add_argument(
        "--click-sequence",
        default="",
        help=(
            "Semicolon-separated clicks as ratio_x,ratio_y,delay_after entries. "
            "Example: 0.55,0.48,8;0.62,0.03,1;0.55,0.48,1"
        ),
    )
    parser.add_argument("--log", default="touchhle_auto_click.log")
    parser.add_argument("--attach-pid", type=int, default=0, help="Click an already-running touchHLE process.")
    parser.add_argument(
        "--max-runtime",
        type=float,
        default=0.0,
        help="Terminate the launched process after this many seconds. 0 means wait forever.",
    )
    parser.add_argument(
        "--dump-inspector",
        action="store_true",
        help="Press F11 after the configured clicks so touchHLE writes zombie_farm_inspector.txt.",
    )
    parser.add_argument(
        "--dump-delay",
        type=float,
        default=2.0,
        help="Delay before pressing F11 when --dump-inspector is set.",
    )
    parser.add_argument(
        "--screenshot",
        default="",
        help="Optional path to save a client-area screenshot after the configured clicks.",
    )
    parser.add_argument(
        "--screenshot-delay",
        type=float,
        default=2.0,
        help="Delay before saving --screenshot.",
    )
    return parser.parse_args()


def parse_click_sequence(value: str) -> list[tuple[float, float, float]]:
    sequence: list[tuple[float, float, float]] = []
    for raw_entry in value.split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split(",")]
        if len(parts) not in (2, 3):
            raise ValueError(f"bad click sequence entry {entry!r}")
        ratio_x = float(parts[0])
        ratio_y = float(parts[1])
        delay_after = float(parts[2]) if len(parts) == 3 else 0.0
        sequence.append((ratio_x, ratio_y, delay_after))
    return sequence


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    exe = Path(args.exe)
    if not exe.is_absolute():
        exe = repo / exe
    ipa = Path(args.ipa)
    log_path = repo / args.log

    proc: subprocess.Popen[bytes] | None = None
    pid = args.attach_pid
    if pid == 0:
        command = [str(exe), str(ipa), f"--device-family={args.device_family}"]
        log = log_path.open("wb")
        proc = subprocess.Popen(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
        pid = proc.pid
        print(f"started pid={pid}, log={log_path}")

    hwnd = find_window_for_process(pid, args.title, args.startup_timeout)
    print(f"found hwnd=0x{hwnd:x}, title={window_text(hwnd)!r}")
    if args.wait_log_pattern:
        deadline = time.time() + args.wait_log_timeout
        while time.time() < deadline:
            if log_path.exists() and args.wait_log_pattern in log_path.read_text(
                errors="ignore"
            ):
                print(f"matched log pattern={args.wait_log_pattern!r}")
                break
            if proc is not None and proc.poll() is not None:
                print(f"process exited while waiting for log pattern, code={proc.returncode}")
                break
            time.sleep(0.2)
        else:
            print(f"timed out waiting for log pattern={args.wait_log_pattern!r}")
    time.sleep(args.initial_delay)

    sequence = parse_click_sequence(args.click_sequence)
    if sequence:
        for index, (ratio_x, ratio_y, delay_after) in enumerate(sequence):
            x, y = click_window_center(hwnd, ratio_x, ratio_y)
            print(
                f"clicked sequence {index + 1}/{len(sequence)} "
                f"ratio=({ratio_x}, {ratio_y}) screen=({x}, {y})"
            )
            if delay_after > 0:
                time.sleep(delay_after)
    else:
        for index in range(args.clicks):
            x, y = click_window_center(hwnd, args.center_ratio_x, args.center_ratio_y)
            print(f"clicked center {index + 1}/{args.clicks} at screen ({x}, {y})")
            if index + 1 < args.clicks:
                time.sleep(args.interval)

    if args.screenshot:
        time.sleep(args.screenshot_delay)
        from PIL import ImageGrab

        left, top, width, height = client_rect_on_screen(hwnd)
        image = ImageGrab.grab((left, top, left + width, top + height))
        screenshot_path = Path(args.screenshot)
        if not screenshot_path.is_absolute():
            screenshot_path = repo / screenshot_path
        image.save(screenshot_path)
        print(f"saved screenshot={screenshot_path}")

    if args.dump_inspector:
        time.sleep(args.dump_delay)
        dump_inspector(hwnd)
        print("requested inspector dump with F11")

    if proc is not None:
        if args.max_runtime <= 0:
            return proc.wait()
        try:
            return proc.wait(timeout=args.max_runtime)
        except subprocess.TimeoutExpired:
            print(f"max runtime reached; terminating pid={proc.pid}")
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
                return 0
            except subprocess.TimeoutExpired:
                print(f"pid={proc.pid} did not terminate; killing")
                proc.kill()
                proc.wait()
                return 0
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
