"""Read-only, zero-model-turn quota reader, measured on agy 1.4.12.

The provider exposes separate quota groups. No default group is safe: Argon can
be exhausted while the general Gemini bucket still reports 100% remaining.
"""
from __future__ import annotations

import json
import math
import subprocess
import time
from datetime import datetime


class AgyUsageReader:
    def __init__(self, window='five_hour', limit_id=None, *, run=subprocess.run, now=time.time):
        self.window, self.limit_id, self.run, self.now = window, limit_id, run, now

    def _read(self):
        from .governor import Reading, FIVE_HOUR, SEVEN_DAY
        if not self.limit_id:
            raise ValueError('agy_usage requires an explicit group limit_id')
        result = self.run(['agy', '-p', '/usage', '--output-format', 'json'],
                          capture_output=True, text=True, timeout=30, check=False)
        if result.returncode != 0:
            raise ValueError('agy quota command failed')
        data = json.loads(result.stdout)
        if data.get('status') != 'SUCCESS' or data.get('num_turns') != 0:
            raise ValueError('agy quota response is not a zero-turn success')
        command = data.get('command') or {}
        if command.get('name') != 'usage':
            raise ValueError('agy response is not usage')
        groups = [g for g in command['data']['groups'] if g.get('name') == self.limit_id]
        if len(groups) != 1:
            raise ValueError('agy quota group absent or ambiguous')
        readings = {}
        for b in groups[0]['buckets']:
            window = {'5h': FIVE_HOUR, 'weekly': SEVEN_DAY}.get(b.get('window'))
            if window is None or window in readings:
                raise ValueError('agy quota window unsupported or duplicated')
            fraction = b.get('remaining_fraction')
            if type(fraction) not in (float, int) or not math.isfinite(fraction) or not 0 <= fraction <= 1:
                raise ValueError('agy remaining quota malformed')
            stamp = b.get('reset_time')
            if not isinstance(stamp, str) or not stamp.endswith('Z'):
                raise ValueError('agy reset timestamp malformed')
            reset = datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
            readings[window] = Reading(pct=(1-fraction)*100, at=self.now(), ok=True,
                                      reset_at=reset, source='agy_usage', limit_id=self.limit_id)
        if not readings:
            raise ValueError('agy quota has no usable windows')
        return readings

    def read_all(self):
        from .governor import Reading
        try:
            return self._read()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
            return {self.window: Reading(ok=False, source='agy_usage',
                                        error='agy quota could not be verified', limit_id=self.limit_id)}

    def read(self):
        from .governor import Reading
        return self.read_all().get(self.window, Reading(ok=False, source='agy_usage',
                                                       error='agy selected window absent', limit_id=self.limit_id))
