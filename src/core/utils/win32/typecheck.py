"""
Type checking helpers for ctypes
Required for private types (_CArgObject, _CFunctionType, _Pointer) not exposed to the public API
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # NOTE: this is an internal ctypes type that does not exist during runtime
    from ctypes import _CArgObject as CArgObject  # type: ignore[reportPrivateUsage]
    from ctypes import _CFunctionType as CFunctionType  # type: ignore[reportPrivateUsage]
    from ctypes import _Pointer as CPointer  # type: ignore[reportPrivateUsage]
else:
    # NOTE: During runtime just use Any placeholders
    CArgObject = Any
    CFunctionType = Any

    class CPointer[T]:
        pass
