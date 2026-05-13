#!/usr/bin/env python3
"""
send_camera_frames.py

Reads frames from a local camera (or video file / MJPEG URL) and forwards
them to a localization_service_host instance that was started with 'none'
as the camera source, so it accepts frames via POST /api/frame.

POST /api/frame with a JPEG body queues a frame for tracking and returns the
most recently computed pose.  POST /api/frame with an empty body returns the
current pose without submitting a new frame — useful for polling after a frame
has been submitted but before the next one is ready.

Response format (both variants):
    {
        "queued": true | false,
        "tracking_state": "OK" | "RECENTLY_LOST" | "LOST" | "NOT_INITIALIZED",
        "pose": {
            "valid": true | false,
            "x": 1.23, "y": 0.45, "z": 0.67,
            "qx": 0.0,  "qy": 0.0,  "qz": 0.0, "qw": 1.0
        }
    }

Usage
-----
    python3 send_camera_frames.py [options]

Examples
--------
    # Default webcam → local service
    python3 send_camera_frames.py

    # /dev/video2, remote service, 15 fps
    python3 send_camera_frames.py --camera /dev/video2 \\
        --server http://192.168.1.10:11142 --fps 15

    # Pre-recorded video file (plays back at 30 fps)
    python3 send_camera_frames.py --camera recording.mp4 --fps 30

    # Show a live preview window (press q to quit)
    python3 send_camera_frames.py --show

Dependencies
------------
    pip install opencv-python requests
"""

import argparse
import json
import signal
import sys
import time

import cv2
import requests


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SERVER  = "http://localhost:11142"
DEFAULT_FPS     = 30
DEFAULT_QUALITY = 80   # JPEG quality 0-100; lower = smaller payload


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Forward camera frames to the localization service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--camera", default="0",
        help="Camera source: device index, /dev/videoX, file path, or URL "
             "(default: 0)",
    )
    p.add_argument(
        "--server", default=DEFAULT_SERVER,
        help=f"Localization service base URL (default: {DEFAULT_SERVER})",
    )
    p.add_argument(
        "--fps", type=float, default=DEFAULT_FPS,
        help=f"Target send rate in frames/sec (default: {DEFAULT_FPS})",
    )
    p.add_argument(
        "--quality", type=int, default=DEFAULT_QUALITY,
        help=f"JPEG encode quality 0-100 (default: {DEFAULT_QUALITY})",
    )
    p.add_argument(
        "--show", action="store_true",
        help="Display a live preview window (press q to quit)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Camera open helper
# ---------------------------------------------------------------------------
def open_camera(source: str) -> cv2.VideoCapture:
    """Open a camera by device index, /dev/videoX path, file, or URL."""
    if source.isdigit():
        return cv2.VideoCapture(int(source), cv2.CAP_V4L2)
    if source.startswith("/dev/video"):
        return cv2.VideoCapture(source, cv2.CAP_V4L2)
    return cv2.VideoCapture(source)


# ---------------------------------------------------------------------------
# Pose formatting
# ---------------------------------------------------------------------------
def format_pose(data: dict) -> str:
    """Return a one-line summary of a /api/frame response."""
    state = data.get("tracking_state", "?")
    pose  = data.get("pose", {})
    if pose.get("valid"):
        return (
            f"[{state}]  "
            f"x={pose['x']:+.3f}  y={pose['y']:+.3f}  z={pose['z']:+.3f}"
        )
    return f"[{state}]  (no valid pose)"


# ---------------------------------------------------------------------------
# Single-shot localization helper
# (illustrates the empty-body poll pattern)
# ---------------------------------------------------------------------------
def query_pose(session: requests.Session, frame_url: str,
               timeout: float = 1.0) -> dict | None:
    """
    POST with empty body to retrieve the current pose without submitting a frame.
    Returns the parsed JSON dict or None on error.
    """
    try:
        resp = session.post(frame_url, data=b"", timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()

    frame_url      = f"{args.server}/api/frame"
    frame_interval = 1.0 / max(args.fps, 0.1)
    encode_params  = [cv2.IMWRITE_JPEG_QUALITY, args.quality]

    # Open camera
    cap = open_camera(args.camera)
    if not cap.isOpened():
        print(f"ERROR: could not open camera: {args.camera}", file=sys.stderr)
        sys.exit(1)

    # Clean Ctrl-C shutdown
    running = True

    def on_sigint(_sig, _frame):
        nonlocal running
        print("\nStopping...")
        running = False

    signal.signal(signal.SIGINT, on_sigint)

    # Re-use one HTTP session for connection keep-alive
    session = requests.Session()

    frames_sent    = 0
    frames_dropped = 0
    t_start        = time.monotonic()

    print(f"Camera  : {args.camera}")
    print(f"Server  : {frame_url}")
    print(f"Target  : {args.fps:.1f} fps, JPEG quality {args.quality}")
    print("Press Ctrl+C to stop.\n")

    while running:
        t_loop = time.monotonic()

        ret, frame = cap.read()
        if not ret:
            print("\nCamera read failed or end of file reached.")
            break

        # Timestamp in milliseconds — same unit as TrackMonocular's tframe
        ts_ms = time.monotonic() * 1000.0

        ok, buf = cv2.imencode(".jpg", frame, encode_params)
        if not ok:
            continue

        try:
            resp = session.post(
                frame_url,
                data=buf.tobytes(),
                params={"ts": f"{ts_ms:.3f}"},
                headers={"Content-Type": "image/jpeg"},
                timeout=0.5,
            )
            if resp.status_code == 200:
                frames_sent += 1
                try:
                    print(f"\r  {format_pose(resp.json())}    ", end="", flush=True)
                except (json.JSONDecodeError, KeyError):
                    pass
            elif resp.status_code == 503:
                # Tracker still processing the previous frame — drop this one.
                # This is normal at startup or during heavy processing.
                frames_dropped += 1
            else:
                print(
                    f"\n[warn] POST /api/frame → HTTP {resp.status_code}: "
                    f"{resp.text[:120]}"
                )
        except requests.exceptions.Timeout:
            frames_dropped += 1
        except requests.exceptions.ConnectionError as exc:
            print(f"\n[error] Connection lost: {exc}")
            break

        if args.show:
            cv2.imshow("send_camera_frames", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        # Pace sending to the target fps
        sleep_for = frame_interval - (time.monotonic() - t_loop)
        if sleep_for > 0:
            time.sleep(sleep_for)

    # Shutdown
    cap.release()
    if args.show:
        cv2.destroyAllWindows()

    elapsed = max(time.monotonic() - t_start, 1e-3)
    print(
        f"\nDone.  {frames_sent} frames sent, {frames_dropped} dropped"
        f" over {elapsed:.1f}s"
        f" ({frames_sent / elapsed:.1f} fps effective)"
    )


# ---------------------------------------------------------------------------
# Single-shot localization example
# ---------------------------------------------------------------------------
# Typical usage pattern for a device that wants one position fix:
#
#   session = requests.Session()
#   url     = "http://host:11142/api/frame"
#
#   # 1. Submit a frame.
#   _, buf = cv2.imencode(".jpg", frame)
#   r = session.post(url, data=buf.tobytes(),
#                    params={"ts": f"{time.monotonic()*1000:.3f}"},
#                    headers={"Content-Type": "image/jpeg"})
#   data = r.json()                        # pose from the *previous* frame
#
#   # 2. Poll with empty body until tracking_state is OK.
#   for _ in range(10):
#       data = query_pose(session, url)
#       if data and data["pose"]["valid"]:
#           break
#       time.sleep(0.05)
#
#   print(data["pose"])

if __name__ == "__main__":
    main()
