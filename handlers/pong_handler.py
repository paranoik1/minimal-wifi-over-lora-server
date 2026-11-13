from handlers.base import HandlerPayloadError, ResponseType, handler_client_request, _ReturnHandlerType


@handler_client_request(lambda payload: payload == "ping")
def handle_pong(payload: str) -> _ReturnHandlerType:
    return "pong", ResponseType.TEXT


@handler_client_request(lambda p: p == "test")
def handle_test(p: str) -> _ReturnHandlerType:
    try:
        from faker import Faker
    except ImportError:
        raise HandlerPayloadError("Not installed Faker")

    fake = Faker("ru")
    text = fake.text(1000)
    with open("test.txt", "w") as fp:
        fp.write(text)
    return text, ResponseType.TEXT
