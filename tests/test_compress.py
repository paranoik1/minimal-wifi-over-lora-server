import sys
from pathlib import Path
BASE_DIR = Path(__file__).parent.parent
sys.path.append(str(BASE_DIR))

from core.compress import markdown_compressor
from core.packet import MessageType, Packet, PacketFlags
from user_session import UserSession, get_compressor
from handlers import ResponseType


def test_compress():
    with open("response_test.md", "rb") as fp:
        handler_response = fp.read()

    response_type = ResponseType.MARKDOWN

    # compressed1 = markdown_compressor.compress(response[:230])
    # compressed2 = markdown_compressor.compress(response[230:245])
    # decoded = markdown_compressor.decompress_frames(compressed1 + compressed2).decode("utf-8", errors="replace")
    # print()
    req_pkt = Packet(0, 1, 1, "url".encode(), MessageType.RESPONSE_SERVER, 0)
    
    packets = UserSession(None, 1, 2)._create_response_packets(
        req_pkt,
        handler_response,
        response_type
    )
    compressor = get_compressor(response_type)

    is_full_compressed = bool(req_pkt.flags & PacketFlags.FLAG_RESPONSE_NEEDED_FULL_PAYLOAD_COMPRESSED)

    client_received_response = b""
    compressed_result = b""
    for pkt in packets:
        compressed_result += pkt.payload
        if not is_full_compressed:
            client_received_response += compressor.decompress_frames(pkt.payload)

    if is_full_compressed:
        client_received_response = compressor.decompress(compressed_result)

    print(f"{len(client_received_response) = }\n{len(handler_response) = }\n{len(compressed_result) = }\nis_equal =", client_received_response == handler_response)
    assert client_received_response == handler_response


test_compress()
