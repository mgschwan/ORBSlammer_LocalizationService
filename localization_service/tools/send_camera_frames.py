#!/usr/bin/env python3
"""
send_camera_frames.py

Reads frames from a local camera (or video file / MJPEG URL) and forwards
them to a localization_service_host instance that was started with 'none'
as the camera source, so it accepts frames via POST /api/frame.

Simultaneously subscribes to the SSE pose stream (/api/stream/pose) and
prints the current position in the terminal.

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
import threading
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
# Background SSE pose listener
# ---------------------------------------------------------------------------
def pose_listener(server: str, stop: threading.Event) -> None:
    """Connect to /api/stream/pose and print pose updates to stdout."""
    url = f"{server}/api/stream/pose"
    while not stop.is_set():
        try:
            with requests.get(url, stream=True, timeout=5) as resp:
                for raw in resp.iter_lines():
                    if stop.is_set():
                        return
                    if not raw or not raw.startswith(b"data: "):
                        continue
                    try:
                        data = json.loads(raw[6:])
                    except json.JSONDecodeError:
                        continue
                    if data.get("valid"):
                        print(
                            f"\r  Pose  "
                            f"x={data['x']:+.3f}  "
                            f"y={data['y']:+.3f}  "
                            f"z={data['z']:+.3f}    ",
                            end="", flush=True,
                        )
                    else:
                        print(
                            "\r  [tracking lost]                              ",
                            end="", flush=True,
                        )
        except requests.exceptions.ConnectionError:
            if not stop.is_set():
                time.sleep(1)   # retry after a short pause
        except Exception as exc:
            if not stop.is_set():
                print(f"\n[pose thread] {exc}")
            return


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
    stop = threading.Event()

    def on_sigint(_sig, _frame):
        print("\nStopping...")
        stop.set()

    signal.signal(signal.SIGINT, on_sigint)

    # Pose display thread
    pose_thread = threading.Thread(
        target=pose_listener, args=(args.server, stop), daemon=True
    )
    pose_thread.start()

    # Re-use one HTTP session for connection keep-alive
    session = requests.Session()

    frames_sent    = 0
    frames_dropped = 0
    t_start        = time.monotonic()

    print(f"Camera  : {args.camera}")
    print(f"Server  : {frame_url}")
    print(f"Target  : {args.fps:.1f} fps, JPEG quality {args.quality}")
    print("Press Ctrl+C to stop.\n")

    while not stop.is_set():
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
            elif resp.status_code == 503:
                # Tracker is still processing the previous frame — drop this one.
                # This is normal at startup or during heavy processing; no action needed.
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
    stop.set()
    cap.release()
    if args.show:
        cv2.destroyAllWindows()

    elapsed = max(time.monotonic() - t_start, 1e-3)
    print(
        f"\nDone.  {frames_sent} frames sent, {frames_dropped} dropped"
        f" over {elapsed:.1f}s"
        f" ({frames_sent / elapsed:.1f} fps effective)"
    )


if __name__ == "__main__":
    main()
