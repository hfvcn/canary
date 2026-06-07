"""Connector module — imports and calls dormant_module but is NOT reachable from main."""

import dormant_module


def connect() -> str:
    return dormant_module.dormant_action()
