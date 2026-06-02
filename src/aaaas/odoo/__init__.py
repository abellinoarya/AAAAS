"""The Odoo tool layer: a typed client over pluggable backends.

``OdooClient`` is the high-level API the tools use. It talks to an
``OdooBackend`` — either ``XmlRpcBackend`` (a real Odoo instance) or
``InMemoryBackend`` (a faithful fake for dev, demos, and tests). Both
implement the same ``execute_kw`` contract, so nothing above this layer
knows or cares which one is in play.
"""
from .client import OdooClient, OdooBackend, XmlRpcBackend, InMemoryBackend
from . import models

__all__ = [
    "OdooClient",
    "OdooBackend",
    "XmlRpcBackend",
    "InMemoryBackend",
    "models",
]
