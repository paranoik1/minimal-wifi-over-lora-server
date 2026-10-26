from .register import handler_client_request


@handler_client_request(lambda payload: payload == "ping")
def pong(payload: str):
    return "pong"
