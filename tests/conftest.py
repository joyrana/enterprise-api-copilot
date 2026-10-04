"""Shared test configuration.

Async test functions are run with ``asyncio.run`` by the hook below, so the suite needs
no async plugin (pytest-asyncio was not installable in the environment that built it).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        funcargs = pyfuncitem.funcargs
        names = pyfuncitem._fixtureinfo.argnames
        kwargs: dict[str, Any] = {name: funcargs[name] for name in names}
        asyncio.run(pyfuncitem.obj(**kwargs))
        return True
    return None
