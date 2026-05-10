# SLAM Localization Service

A real-time visual localization service built on [ORB-SLAM3](README_ORB_SLAM.md). It exposes a camera-driven SLAM pipeline over a local HTTP interface, enabling live pose streaming, map management, and camera calibration from any browser or REST client.

## Demo

[![ORBSlammer Localization Service Introduction](https://img.youtube.com/vi/kERIrPdpNNk/0.jpg)](https://youtu.be/kERIrPdpNNk)

## Overview

The service captures frames from a camera (USB, V4L2, or any MJPEG/RTSP URL), runs them through ORB-SLAM3, and publishes the resulting camera pose via Server-Sent Events. A web UI is served directly from the process — no separate web server needed.

Key capabilities:
- **Live localization** against a pre-built map, or **active mapping** to build a new one
- **Pose streaming** at ~30 fps over SSE (`/api/stream/pose`)
- **Map management**: switch between maps, create new maps, download/upload atlas files
- **Camera calibration**: chessboard-based calibration via the web UI, with live preview
- **Floor alignment**: RANSAC-based automatic floor plane detection, or manual pitch/roll adjustment

## Building

### Dependencies

- CMake ≥ 2.8
- OpenCV ≥ 4.4
- Eigen3 ≥ 3.1
- Boost (serialization)
- DBoW2 and g2o (included in `Thirdparty/`)
- Sophus (included in `Thirdparty/`)

### Compile

```bash
# Build Thirdparty libraries first (DBoW2, g2o)
cd Thirdparty/DBoW2 && mkdir -p build && cd build && cmake .. && make -j4
cd ../../../Thirdparty/g2o && mkdir -p build && cd build && cmake .. && make -j4

# Build the project
mkdir -p build && cd build
cmake ..
make -j4 localization_service_host
```

The binary is output to `localization_service/localization_service_host`.

You also need the ORB vocabulary file:

```bash
cd Vocabulary && tar -xf ORBvoc.txt.tar.gz
```

## Running

### Mapping mode (build a new map)

```bash
cd localization_service
./localization_service_host \
    ../Vocabulary/ORBvoc.txt \
    example.yaml \
    /dev/video0
```

Open `http://localhost:11142` to access the web interface. Once the map looks good, download it via **Atlas → Download** (`.osa` file).

### Localization mode (use a saved map)

```bash
./localization_service_host \
    ../Vocabulary/ORBvoc.txt \
    example.yaml \
    /dev/video0 \
    localize_only \
    0
```

The last argument is the map index to relocalize against (default `0`).

### Camera sources

| Source | Example value |
|--------|--------------|
| USB/V4L2 device number | `0` |
| V4L2 device path | `/dev/video2` |
| MJPEG / RTSP stream | `http://192.168.1.10:4747/video` |
| Tello drone | use `tools/tello_camera_server.py` then point to its output URL |

## HTTP API

All endpoints are served on port **11142**.

### Status & control

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/status` | JSON snapshot of current system state (see below) |
| `GET` | `/pause` | Pause frame processing |
| `GET` | `/resume` | Resume frame processing |
| `GET` | `/loc` | Switch to localization mode (disables new map creation) |
| `GET` | `/map` | Switch to mapping mode |
| `GET` | `/switchmap?id=N` | Switch active map to id `N` |
| `GET` | `/newmap` | Create and switch to a new empty map |
| `GET` | `/allow_new_maps?enable=true\|false` | Enable or disable automatic new-map creation when tracking is lost |

`/api/status` response:

```json
{
  "localizationMode": false,
  "allowMapCreation": true,
  "paused": false,
  "currentMapId": 1,
  "maps": [
    { "id": 0, "keyframes": 142, "mappoints": 3891 },
    { "id": 1, "keyframes": 67,  "mappoints": 1204 }
  ]
}
```

### Pose stream (SSE)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/stream/pose` | Server-Sent Events stream of camera pose at ~30 fps |

Each event is a JSON object:

```json
{ "valid": true, "x": 0.1, "y": -0.3, "z": 0.8, "qx": 0, "qy": 0, "qz": 0, "qw": 1 }
```

When tracking is lost: `{ "valid": false }`

### Map

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/map/points` | All map points as a JSON array `[{x,y,z}, ...]` |
| `GET` | `/api/map/auto_align_floor` | RANSAC floor plane detection and rotation correction |
| `GET` | `/api/map/align_floor?pitch=P&roll=R` | Manual floor alignment (radians) |

### Atlas (map files)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/atlas/download` | Download current atlas as `atlas.osa` |
| `POST` | `/api/atlas/upload` | Upload a `.osa` file to replace the current atlas |

### Camera calibration

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/calibrate/mode?enable=true` | Enter calibration mode (pauses SLAM) |
| `GET` | `/api/calibrate/mode?enable=false` | Exit calibration mode |
| `GET` | `/api/calibrate/capture[?size=S]` | Capture current frame for calibration (square size in metres) |
| `GET` | `/api/calibrate/status` | JSON: capture count, last result, active state |
| `GET` | `/api/calibrate/image` | JPEG of the last captured frame with corners drawn |
| `GET` | `/api/calibrate/compute` | Run calibration from captured frames, apply to SLAM |
| `GET` | `/api/calibrate/apply?fx=..&fy=..&cx=..&cy=..&k1=..&k2=..&p1=..&p2=..&k3=..` | Apply known intrinsics directly |

### Static files

Everything else under `/` is served from `localization_service/html/`. The default page (`/`) loads `index.html`.

## Console commands

While the service is running, commands can be typed directly in the terminal:

| Command | Action |
|---------|--------|
| `loc` / `localize` | Switch to localization mode |
| `map` / `mapping` | Switch to mapping mode |
| `newmaps_on` | Enable automatic new-map creation on tracking loss |
| `newmaps_off` | Disable automatic new-map creation (continuously retry relocalization instead) |
| `pause` | Pause processing |
| `resume` | Resume processing |
| `quit` / `exit` | Shut down cleanly |

## Configuration

Camera intrinsics and the active map can be set at runtime through the web interface — a correctly tuned YAML file is not required to get started.

- **Calibration**: use the **Calibration** page to capture chessboard frames and compute intrinsics, or enter known values directly via `/api/calibrate/apply`. The result is applied to the running SLAM system immediately.
- **Map**: upload a previously saved `.osa` atlas file via **Atlas → Upload**, or download the current map via **Atlas → Download** to reuse across sessions.

A minimal YAML file is still needed to launch the process (it sets sensor type, image size, and ORB feature count). See `localization_service/example.yaml` for a starting template. The format follows the ORB-SLAM3 settings specification — refer to [README_ORB_SLAM.md](README_ORB_SLAM.md) for full documentation.

### Custom YAML parameters

The following keys extend the standard ORB-SLAM3 settings file with project-specific behaviour.

#### Loop closing & map merging

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `loopClosing` | `0` or `1` | `1` | Enable or disable the loop-closing / map-merging thread. Even when `0`, keyframes are still inserted into the place-recognition database so that relocalization works. |
| `mergeMinBoWMatches` | int | `10` | Minimum number of BoW descriptor matches required between a query keyframe and a merge candidate before geometric validation is attempted. Lower values make merging easier across maps with sparse visual overlap (typical for monocular). |
| `mergeMinBoWInliers` | int | `7` | Minimum number of RANSAC inliers required during Sim3 estimation. Must be ≤ `mergeMinBoWMatches`. |
| `mergeMinSim3Inliers` | int | `20` | Minimum inliers after Sim3 graph optimisation. |
| `mergeMinProjMatches` | int | `50` | Minimum projection matches (coarse pass) after Sim3 alignment. |
| `mergeMinProjOptMatches` | int | `80` | Minimum projection matches (refined pass). This is the final gate before a merge is confirmed. |

The merge pipeline is cascaded: a candidate must pass every stage in order. The Sim3 and projection stages remain strict even when the BoW thresholds are lowered, so false-positive merges are unlikely. Additionally, a merge is only triggered after **3 consecutive keyframes** all pass the full pipeline.

#### Map creation behaviour

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| *(no YAML key — runtime only)* | — | — | Whether to create a new map when tracking is lost is controlled at runtime via `/allow_new_maps` or the `newmaps_on` / `newmaps_off` console commands. When the service is started in `localize_only` mode this is automatically disabled. |

## Project structure

```
localization_service/
  src/
    localization_service_host.cc  — main(): arg parsing, SLAM init, tracking loop
    slam_state.cc                 — shared atomic flags and pose state
    calibration_manager.cc        — chessboard calibration logic
    web_server.cc                 — HTTP server and all route handlers
  include/localization_service/
    config.h                      — port define (11142) and tuning constants
    slam_state.h                  — LifecycleFlags, PoseState
    calibration_manager.h         — CalibrationManager
    web_server.h                  — WebServer
  html/
    index.html                    — main web UI
    viewer.html                   — pose and map viewer
    calibration.html              — calibration assistant
  tools/
    tello_camera_server.py        — relay server for Tello drone camera
  example.yaml                    — sample camera configuration
```

## Underlying technology

This service is built on top of **ORB-SLAM3**, a feature-based monocular/stereo/RGB-D SLAM system developed at the University of Zaragoza. See [README_ORB_SLAM.md](README_ORB_SLAM.md) for the original documentation and [ORB-SLAM3 paper](https://arxiv.org/abs/2007.11898) for the academic reference.

Modifications to the ORB-SLAM3 core:
- Pangolin visualizer made optional (no display required)
- `ForceRelocalization()`, `SwitchToMap()`, and `SetAllowMapCreation()` APIs added
- `ChangeCalibration()` API added for runtime intrinsics updates
- KeyFrameDatabase scoped correctly per-map to fix cross-map relocalization
- New-map creation on tracking loss is now optional and togglable at runtime; when disabled the system continuously retries relocalization against the existing map
- Loop closing enabled by default; merge detection thresholds are configurable via YAML to handle monocular environments with sparse cross-map BoW overlap
- Fixed an infinite-loop bug in `KeyFrameDatabase::DetectNBestCandidates` triggered by bad keyframes mid-iteration
