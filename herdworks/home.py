import os
from pathlib import Path


def hw_home():
    return Path(os.environ.get("HW_HOME", Path.home() / ".herdworks")).expanduser().resolve()


def sandbox_setting(data):
    value = data.get('sandbox', 'on')
    if value not in ('on', 'off'):
        raise ValueError('sandbox must be on or off')
    return value
