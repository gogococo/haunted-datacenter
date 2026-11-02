"""Explicit local-only transport; never infer local mode from a failed cloud call."""
import os
from urllib.parse import urlsplit


def enabled():
    active = os.environ.get('HAUNTED_LOCAL_WORKERS') == '1'
    if active and os.environ.get('PUBLIC_DEPLOYMENT', '').lower() in ('1', 'true', 'yes'):
        raise ValueError('Local Docker workers cannot be used in a public deployment.')
    return active


def endpoint(service):
    if not enabled():
        raise ValueError('Local Docker workers are not enabled.')
    variable = {'caretaker': 'CARETAKER_WORKER_URL', 'cooling': 'LOCAL_COOLING_URL'}[service]
    value = os.environ.get(variable, '').rstrip('/')
    parsed = urlsplit(value)
    # Fixed Compose service names only. No arbitrary HTTP hosts or redirects.
    if value != 'http://' + service + ':8000' or parsed.username or parsed.password:
        raise ValueError('Use the private Docker ' + service + ' service on port 8000.')
    return value


def worker_label():
    return 'local Docker CPU' if enabled() else 'Serverless GPU'
