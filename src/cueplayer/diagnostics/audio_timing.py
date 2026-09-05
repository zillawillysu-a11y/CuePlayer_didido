"""Opt-in bounded callback observations, never a playback clock.

One callback writer; non-RT readers skip rows overwritten during a snapshot.
No logging, locks, growing containers or native device calls in record(). Python
scalar arithmetic still has interpreter overhead: this is not a zero-cost probe.
"""
from array import array


FIELDS = (
    "sequence", "stream_epoch", "transport_generation", "host_monotonic",
    "current_time", "dac_time", "frames", "callback_rate", "processing_rate",
    "source_rate", "start_frame", "end_frame", "status_flags", "reason",
    "execution_seconds",
)
# Reasons describe render state, NOT a signal-level assertion that all buses are silent.
REASONS = {0: "render", 1: "paused", 2: "exception", 3: "music_not_ready", 4: "end"}


class AudioTimingTrace:
    def __init__(self, capacity: int = 512):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._rows = array("d", [0.0]) * (capacity * len(FIELDS))
        self._sequence = 0

    def record(self, epoch, generation, host, current, dac, frames, callback_rate,
               processing_rate, source_rate, start, end, flags, reason, execution):
        seq = self._sequence + 1
        i = ((seq - 1) % self.capacity) * len(FIELDS)
        rows = self._rows
        rows[i] = -1  # invalidate before reuse; publish sequence last
        rows[i + 1] = epoch
        rows[i + 2] = generation
        rows[i + 3] = host
        rows[i + 4] = current
        rows[i + 5] = dac
        rows[i + 6] = frames
        rows[i + 7] = callback_rate
        rows[i + 8] = processing_rate
        rows[i + 9] = source_rate
        rows[i + 10] = start
        rows[i + 11] = end
        rows[i + 12] = flags
        rows[i + 13] = reason
        rows[i + 14] = execution
        rows[i] = seq
        self._sequence = seq

    def snapshot(self):
        """Allocate/format only on the reporting thread; no consistency lock."""
        latest = self._sequence
        result = []
        for seq in range(max(1, latest - self.capacity + 1), latest + 1):
            i = ((seq - 1) % self.capacity) * len(FIELDS)
            if self._rows[i] != seq:
                continue
            row = self._rows[i:i + len(FIELDS)]
            if row[0] == seq and self._rows[i] == seq:
                result.append(dict(zip(FIELDS, row)))
        return result
