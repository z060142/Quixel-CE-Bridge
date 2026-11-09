# -*- coding: utf-8 -*-
"""Robust access to `sandbox` command groups.

CRYENGINE registers each command group (general, object, selection, ...) as a
pseudo submodule `sys.modules["sandbox.<name>"]` and auto-imports it into
`__main__` ("from sandbox import <name>"). Whether the group is also set as an
attribute of the `sandbox` package itself varies between builds, so all three
locations are checked.
"""
import sys

_cache = {}


def group(name):
    """The module object for a `sandbox` command group, or None."""
    if name in _cache:
        return _cache[name]
    found = None
    try:
        import sandbox
        found = getattr(sandbox, name, None)
    except ImportError:
        return None
    if found is None:
        import __main__
        found = getattr(__main__, name, None)
    if found is None:
        found = sys.modules.get("sandbox." + name)
    _cache[name] = found
    return found
