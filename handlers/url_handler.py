import re

import bs4
import httpx
from markdownify import markdownify

from .register import handler_client_request

url_regex = re.compile(r"^https?://")


@handler_client_request(lambda payload: url_regex.match(payload) != None)
def url_handler(payload: str):
    # NOTE: в будущем можно будет задавать какие то параметры внутрь payload
    # например: https://habr.com/articles/123123 %%% METHOD=POST
    url = payload
    client = httpx.Client(http2=True)

    response = client.get(url)
    content_raw = response.read()
    content_html = content_raw.decode()

    content_md = markdownify(content_html)
    return content_md
