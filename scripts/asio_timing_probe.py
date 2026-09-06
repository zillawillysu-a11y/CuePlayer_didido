"""Bounded, silent ASIO driver probe; not a physical loopback certification.

Opens one explicitly named ASIO output at its current default rate. Does not
load projects, change preferences, or send music/LTC/MIDI. JSON is written only
after closing the stream. Run outside pytest, on the hardware being evaluated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import platform
from pathlib import Path
import time

from cueplayer.playback.devices import sd
from cueplayer.diagnostics.audio_timing import AudioTimingTrace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True, help='Exact ASIO output name')
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 10:
        parser.error('--seconds must be between 1 and 10')
    if args.output.exists():
        parser.error('output already exists; use a new report path')
    devices = sd.query_devices()
    apis = sd.query_hostapis()
    matches = [(i, dict(d)) for i, d in enumerate(devices)
               if d['name'] == args.device and d['max_output_channels'] > 0
               and apis[d['hostapi']]['name'] == 'ASIO']
    if len(matches) != 1:
        parser.error(f'expected exactly one matching ASIO output; got {len(matches)}')
    index, device = matches[0]
    rate = float(device['default_samplerate'])
    trace = AudioTimingTrace(32768)
    total_frames = 0
    callback_count = 0
    status_count = 0

    def callback(outdata, frames, info, status):
        nonlocal total_frames, callback_count, status_count
        started = time.monotonic()
        outdata.fill(0)
        trace.record(1, 0, started, info.currentTime, info.outputBufferDacTime,
                     frames, rate, rate, rate, total_frames,
                     total_frames + frames, status._flags, 0,
                     time.monotonic() - started)
        total_frames += frames
        callback_count += 1
        status_count += bool(status)

    with sd.OutputStream(device=index, samplerate=rate, channels=device['max_output_channels'],
                         dtype='float32', blocksize=0, latency='low', callback=callback) as stream:
        start_time = stream.time
        time.sleep(args.seconds)
        observed = {'samplerate': stream.samplerate, 'latency': stream.latency,
                    'active': stream.active, 'cpu_load': stream.cpu_load,
                    'start_time': start_time, 'end_time': stream.time}
    rows = trace.snapshot()
    valid = [r for r in rows if math.isfinite(r['dac_time']) and r['dac_time'] > 0
             and math.isfinite(r['current_time'])]
    queued = [r['dac_time'] - r['current_time'] for r in valid]
    gaps = [b['dac_time'] - a['dac_time'] - a['frames'] / rate
            for a, b in zip(rows, rows[1:])
            if math.isfinite(a['dac_time']) and math.isfinite(b['dac_time'])]
    report = {
        'utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'silent PortAudio ASIO output only; no AudioEngine, physical loopback, pitch or routing verification',
        'python': platform.python_version(),
        'dependencies': {name: importlib.metadata.version(name)
                         for name in ('sounddevice', 'numpy', 'PySide6', 'av')},
        'portaudio': sd.get_portaudio_version(), 'device_index': index, 'device': device,
        'requested_rate': rate, 'duration_requested': args.seconds, 'stream': observed,
        'summary': {
            'callbacks': callback_count, 'retained_callbacks': len(rows),
            'frames': total_frames, 'callbacks_with_status': status_count,
            'valid_dac_timestamps': len(valid),
            'negative_queue_intervals': sum(q < 0 for q in queued),
            'queue_seconds_min': min(queued, default=None),
            'queue_seconds_max': max(queued, default=None),
            'max_abs_dac_continuity_error_seconds': max(map(abs, gaps), default=None),
            'block_frames': sorted({int(r['frames']) for r in rows}),
        },
        'callbacks': rows,
    }
    # Strict JSON: unavailable native timestamps are represented by null.
    def clean(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as report_file:
        json.dump(clean(report), report_file, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(clean(report['summary']), indent=2, allow_nan=False))
    print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
