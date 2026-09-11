import time
from collections import deque

# Extra buffer beyond the strict N-calls/60s window, to account for clock/network
# jitter pushing a call right up against the provider's boundary.
SAFETY_MARGIN_SECONDS = 1.0


class RateLimiter:
    """Sliding-window limiter: never allows more than `calls_per_minute` calls in
    any rolling 60-second window. A fixed-interval limiter (sleep 60/N between
    calls) is NOT equivalent to this and can still get rejected right at the
    window boundary (confirmed against iTick's free tier: 5 calls spaced exactly
    12s apart got a 429 on the 6th call)."""

    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self._call_times: deque[float] = deque()

    def wait(self) -> None:
        now = time.monotonic()

        while self._call_times and now - self._call_times[0] >= 60:
            self._call_times.popleft()

        if len(self._call_times) >= self.calls_per_minute:
            sleep_for = 60 - (now - self._call_times[0]) + SAFETY_MARGIN_SECONDS
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            while self._call_times and now - self._call_times[0] >= 60:
                self._call_times.popleft()

        self._call_times.append(time.monotonic())
