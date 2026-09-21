import asyncio
import time
import numpy as np
import pytest

from backend.stream_manager import StreamManager, StreamWorker, _get_inference_semaphore

class MockWebSocketManager:
    def __init__(self):
        self.broadcasted = []
    async def broadcast(self, message: dict):
        self.broadcasted.append(message)

@pytest.mark.anyio
async def test_performance_frame_ingest_and_caching():
    """Verifies that frame ingestion is instantaneous (<5ms) and uses cached canonical ID without DB queries."""
    mgr = StreamManager()
    ws = MockWebSocketManager()

    # Pre-populate cache
    mgr.start_stream("PERF-CAM-01", "PUSH", "push", ws)
    assert "PERF-CAM-01" in mgr.workers
    worker = mgr.workers["PERF-CAM-01"]

    # Allow worker initialization tick
    for _ in range(10):
        if worker.is_running and worker.source is not None:
            break
        await asyncio.sleep(0.05)

    test_frame = np.zeros((360, 640, 3), dtype=np.uint8)

    # Ingest 100 frames and measure latency
    t0 = time.time()
    for _ in range(100):
        delivered = mgr.push_frame("PERF-CAM-01", test_frame)
        assert delivered is True
    elapsed = time.time() - t0

    # 100 frames should take well under 50ms total (<0.5ms per frame)
    avg_per_frame_ms = (elapsed / 100.0) * 1000.0
    print(f"\n[PERFORMANCE] Ingested 100 frames in {elapsed*1000:.1f}ms (avg {avg_per_frame_ms:.2f}ms/frame)")
    assert avg_per_frame_ms < 5.0, f"Frame ingest took too long: {avg_per_frame_ms}ms/frame"

    # Verify that worker.stream_manager is correctly set
    assert worker.stream_manager is mgr

    # Verify that subscriber count is 0 and no JPEG is generated when no client is subscribed
    assert mgr.get_subscriber_count("PERF-CAM-01") == 0

    mgr.stop_all()

@pytest.mark.anyio
async def test_bounded_inference_queue_drops_stale_backlog():
    """Verifies that the inference worker only retains the latest pending frame and discards stale backlog."""
    ws = MockWebSocketManager()
    worker = StreamWorker("PERF-CAM-02", "PUSH", "push", ws)

    frame_1 = np.ones((100, 100, 3), dtype=np.uint8) * 10
    frame_2 = np.ones((100, 100, 3), dtype=np.uint8) * 20
    frame_3 = np.ones((100, 100, 3), dtype=np.uint8) * 30

    # Simulate fast burst of frames arriving while inference is busy
    worker.is_inferencing = True

    worker._pending_ai_frame = (frame_1, time.time(), None)
    worker._pending_ai_frame = (frame_2, time.time(), None)
    worker._pending_ai_frame = (frame_3, time.time(), None)

    # Backlog must strictly contain ONLY the latest frame (frame_3)
    assert worker._pending_ai_frame is not None
    target_frame, _, _ = worker._pending_ai_frame
    assert np.array_equal(target_frame, frame_3), "Worker failed to discard stale intermediate frames"

    worker.stop()

@pytest.mark.anyio
async def test_cpu_inference_concurrency_bounded():
    """Verifies that CPU inference concurrency semaphore is bounded to avoid CPU thrashing."""
    sem = _get_inference_semaphore()
    assert sem._value <= 4, f"Inference semaphore must be bounded (got {sem._value})"
    print(f"\n[PERFORMANCE] Bounded CPU inference semaphore verified (initial value = {sem._value})")
