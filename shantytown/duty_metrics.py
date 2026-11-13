"""Publish the retained duty census through the existing governor gateway.

# arming: library; called by the already armed stranded-owner-work sweep.
"""
import os

from .duties import metrics
from .governor_metrics import PUSHGATEWAY_ENV, _push
from .host_identity import physical_hostname


def publish(root, *, now=None):
    gateway = os.environ.get(PUSHGATEWAY_ENV)
    if not gateway:
        return False
    try:
        instance = physical_hostname()
        if not instance or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in instance):
            return False
        _push(gateway, 'st_duties', instance, metrics(root, now=now))
        return True
    except Exception:
        # No credential-bearing URL, path, response body or private duty text
        # reaches the supervisor log. Exporter freshness carries the failure.
        return False
