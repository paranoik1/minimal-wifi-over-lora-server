from core.compress import markdown_compressor
from core.packet import MessageType, Packet, PacketFlags
from user_session import UserSession


def test_compress():
    with open("response_test.md", "rb") as fp:
        response = fp.read()

    # compressed1 = markdown_compressor.compress(response[:230])
    # compressed2 = markdown_compressor.compress(response[230:245])
    # decoded = markdown_compressor.decompress_frames(compressed1 + compressed2).decode("utf-8", errors="replace")
    # print()
    req_pkt = Packet(0, 1, 1, "url".encode(), MessageType.RESPONSE_SERVER, PacketFlags.FLAG_COMPRESSED)
    
    packets = UserSession(None, 1, 2)._create_response_packets(
        req_pkt,
        response
    )

    is_full_compressed = bool(req_pkt.flags & PacketFlags.FLAG_RESPONSE_NEDDED_FULL_PAYLOAD_COMPRESSED)

    result_response = b""
    compressed_result = b""
    for pkt in packets:
        compressed_result += pkt.payload
        if not is_full_compressed:
            result_response += markdown_compressor.decompress_frames(pkt.payload)

    if is_full_compressed:
        result_response = markdown_compressor.decompress(compressed_result)

    print(f"{len(result_response)=}, {len(response)=}, {len(compressed_result)=}", result_response == response)
    assert result_response == response
