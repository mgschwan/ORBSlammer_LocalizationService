#pragma once

#include <condition_variable>
#include <deque>
#include <mutex>

#include <opencv2/core/mat.hpp>

namespace localization_service {

struct IngestFrame {
    cv::Mat image;
    double  timestamp{0.0};  // milliseconds (same unit as TrackMonocular tframe)
    bool    hasImu{false};
    float   ax{0}, ay{0}, az{0};  // accelerometer  m/s²
    float   gx{0}, gy{0}, gz{0};  // gyroscope      rad/s
};

// Thread-safe, bounded frame queue shared between the ingest route(s) and the
// main tracking loop.  Bounded to kMaxDepth so a slow tracker never builds up
// a backlog of stale frames.
//
// Option 1: POST /api/frame   → push() one frame per request
// Option 2: multipart stream  → push() in a reader thread (future)
class IngestQueue {
public:
    static constexpr int kMaxDepth = 2;

    // Push a frame. Returns false (frame dropped) if the queue is already full.
    bool push(IngestFrame frame);

    // Block until a frame is available or timeoutUs elapses.
    // Returns false on timeout.
    bool pop(IngestFrame& out, int timeoutUs);

private:
    std::mutex              mtx_;
    std::condition_variable cv_;
    std::deque<IngestFrame> q_;
};

} // namespace localization_service
