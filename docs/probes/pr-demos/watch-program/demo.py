"""Synthetic evidence only; no live reader, deployment or Action."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from shantytown.watch_program import Observation, WatchSpec, evaluate_watch, next_sample_at

spec = WatchSpec.validate(dict(version=1, run_id='fixture', source_digest='a' * 64,
    deployment_receipt='fixture-receipt', identity='fixture-sha-pid-config',
    start=1000, window_seconds=100, sample_seconds=45,
    maximum={'p99_seconds': 6.4875, 'error_fraction': .01}))
rows = [Observation(t, spec.identity, {'p99_seconds': 1.56, 'error_fraction': .0011}) for t in spec.grid()]
print('Original sample grid:', spec.grid())
print('Resume at 1090 -> final sample:', next_sample_at(spec, 1090))
print('Safe but native inactive:', evaluate_watch(spec, rows, now=1100, activation='INACTIVE'))
print('Missing final sample:', evaluate_watch(spec, rows[:-1], now=1100, activation='ACTIVE'))
rows[0].metrics['p99_seconds'] = 8.
del rows[0].metrics['error_fraction']
print('Breach plus missing metric:', evaluate_watch(spec, rows, now=1100, activation='ACTIVE'))
print('No collector, launch, compensation or close operation occurred.')
