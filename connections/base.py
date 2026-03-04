from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class BaseConnection(ABC):

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def read_lines(self) -> AsyncGenerator[str, None]: ...
