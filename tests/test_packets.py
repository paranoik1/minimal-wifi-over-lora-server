import struct
from core.packet import Packet, MessageType


def test_process_received_packets_report():
    report = struct.pack(">H", 7) + b"1,3-5"

    pkt0 = Packet(0, 0, 0, report, MessageType.RECEIVED_PACKETS_REPORT, 0)
    pkt1 = Packet(1, 0, 0, b"6", MessageType.RECEIVED_PACKETS_REPORT, 0)

    session = UserSession(None, 0, 0) # type: ignore
    
    for i in range(0, 10):
        pkt = Packet(i, 0, 0, b"Hello", MessageType.RESPONSE_SERVER, 0)
        session._sended_packets.append(pkt)
        
    session._process_packet(pkt0)
    session._process_packet(pkt1)

