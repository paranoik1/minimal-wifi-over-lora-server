from typing import Callable
from functools import wraps
from core.packet import Packet


PayloadHandler = Callable[[str], str]
CheckHandler = Callable[[str], bool]

_HANDLERS: dict[CheckHandler, PayloadHandler] = {}


def get_all_handlers() -> dict[CheckHandler, PayloadHandler]:
    return _HANDLERS.copy()


def handler_client_request(check_func: CheckHandler):
    def decorator(func):
        _HANDLERS[check_func] = func

        @wraps
        def wrapper(payload: str):
            if check_func(payload):
                func(payload)
        return wrapper
    
    return decorator
