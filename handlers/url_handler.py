import re

import httpx
from trafilatura import extract

from .base import HandlerPayloadError, ResponseType, handler_client_request, _ReturnHandlerType


url_regex = re.compile(r"^https?://")


@handler_client_request(lambda payload: url_regex.match(payload) != None)
def handle_url(payload: str) -> _ReturnHandlerType:
    # NOTE: в будущем можно будет задавать какие то параметры внутрь payload
    # например: https://habr.com/articles/123123 %%% METHOD=POST
    url = payload
    client = httpx.Client(http2=True)

    response = client.get(url)
    if response.status_code != 200:
        raise HandlerPayloadError(f"HTTP Error: {response.status_code}")
    
    content_raw = response.read()
    content_html = content_raw.decode()

    content_md = extract(
        content_html, 
        output_format="markdown", 
        include_images=True, 
        include_links=True, 
        with_metadata=True
    )
    if not content_md:
        raise HandlerPayloadError("trafilatura return None...")
    
    return content_md, ResponseType.MARKDOWN
