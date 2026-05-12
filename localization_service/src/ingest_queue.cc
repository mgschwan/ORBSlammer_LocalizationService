#include "localization_service/ingest_queue.h"

namespace localization_service {

bool IngestQueue::push(IngestFrame frame)
{
    std::unique_lock<std::mutex> lk(mtx_);
    if (static_cast<int>(q_.size()) >= kMaxDepth)
        return false;
    q_.push_back(std::move(frame));
    lk.unlock();
    cv_.notify_one();
    return true;
}

bool IngestQueue::pop(IngestFrame& out, int timeoutUs)
{
    std::unique_lock<std::mutex> lk(mtx_);
    if (!cv_.wait_for(lk,
                      std::chrono::microseconds(timeoutUs),
                      [this]{ return !q_.empty(); }))
        return false;
    out = std::move(q_.front());
    q_.pop_front();
    return true;
}

} // namespace localization_service
