from enum import StrEnum
from functools import wraps
from typing import Callable


class ResponseType(StrEnum):
    MARKDOWN = "markdown"
    TEXT = "text"
    # IMAGE = "image"
    # JSON = "json"


class HandlerPayloadError(Exception):
    def __init__(self, message: str):
        self.message = message

    def __repr__(self) -> str:
        return f"HandlerPayloadError(\"{self.message}\")"


_ReturnHandlerType = tuple[str, ResponseType]
PayloadHandler = Callable[[str], _ReturnHandlerType]
CheckHandler = Callable[[str], bool]

_HANDLERS: dict[CheckHandler, PayloadHandler] = {}


def get_all_handlers() -> dict[CheckHandler, PayloadHandler]:
    return _HANDLERS.copy()


def handler_client_request(check_func: CheckHandler):
    def decorator(func: PayloadHandler):
        _HANDLERS[check_func] = func
        func_annot = func.__annotations__

        if func_annot.get("return") != _ReturnHandlerType:
            raise RuntimeError(f"{func.__name__} не соответствует анотации: return - {_ReturnHandlerType}")

        @wraps
        def wrapper(payload: str):
            if check_func(payload):
                func(payload)

        return wrapper

    return decorator
