import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import lora.queue_packets as queue_packets
from core.compress import default_compressor, markdown_compressor
from core.packet import MessageType, Packet, PacketErrorCodes, PacketFlags
from core.security import decrypt_payload, encrypt_payload
from handlers import get_all_handlers


class UserSession:
    CHUNK_SIZE = 230

    def __init__(self, thread_pool: ThreadPoolExecutor, user_id: int, session_id: int):
        self.user_id = user_id
        self.session_id = session_id
        self._pool = thread_pool
        self._logger = logging.getLogger(f"user_session   {user_id=} {session_id}=")

        self._lock = threading.Lock()

        self._received_packets: list[Packet] = []
        self._sended_packets: list[Packet] = []

    def _call_handler(self, payload: str, pkt: Packet) -> str:
        """Возвращает полученный payload от подходящего handler"""
        for check, handler in get_all_handlers().items():
            if check(payload):
                return handler(payload)

        raise ValueError(f"Не найден нужный handler под данный payload: {payload[:5]}")

    def _create_response_packets(
        self, request_packet: Packet, response: bytes
    ) -> list[Packet]:
        if (
            request_packet.flags
            & PacketFlags.FLAG_RESPONSE_NEDDED_FULL_PAYLOAD_COMPRESSED
        ):
            # FIXME: в будущем
            pass

        compressed_chunks: list[bytes] = []
        chunk_size = self.CHUNK_SIZE
        for i in range(0, len(response), chunk_size):
            chunk = response[i:chunk_size]
            # FIXME: в будущем handler должен будет возвращать информацию о response
            # К примеру, Тип: чтобы определять, какой compressor стоит использовать для него
            chunk_raw = markdown_compressor.compress(chunk)
            compressed_chunks.append(chunk_raw)

        packets: list[Packet] = []
        pkt_current_id = 0
        for i, chunk in enumerate(compressed_chunks):
            pkt_flags = PacketFlags.FLAG_COMPRESSED.value

            if i + 1 != len(compressed_chunks):
                next_chunk = compressed_chunks[i + 1]
            else:
                next_chunk = None
                pkt_flags |= PacketFlags.FLAG_FINAL_PACKET.value

            if (
                len(chunk) < chunk_size
                and next_chunk
                and len(next_chunk) + len(chunk) <= chunk_size
            ):
                payload = chunk + next_chunk
            else:
                payload = chunk

            packet = Packet(
                pkt_current_id,
                self.user_id,
                self.session_id,
                payload,
                MessageType.RESPONSE_PACKET,
                pkt_flags,
            )
            packets.append(packet)

        return packets

    def _process_packet(self, packet: Packet):
        with self._lock:
            self._received_packets.append(packet)

        payload = decrypt_payload(packet.payload)

        if packet.flags & PacketFlags.FLAG_COMPRESSED:
            payload = default_compressor.decompress(payload)

        if packet.msg_type == MessageType.MSG_REQUEST:
            try:
                response_text = self._call_handler(payload, packet)
            except ValueError as ex:
                self._logger.error(f"Ошибка call_handler: {ex}")
                self.send_error_packet(
                    self.user_id,
                    self.session_id,
                    PacketErrorCodes.UNKNOWN_PAYLOAD_COMMAND,
                )
                return

            response_packets = self._create_response_packets(
                packet, response_text.encode()
            )
            for pkt in response_packets:
                queue_packets.send_packets.put(pkt)
                with self._lock:
                    self._sended_packets.append(pkt)
        elif packet.msg_type == MessageType.RECEIVED_PACKETS_REPORT:
            # FIXME: реализовать
            pass
        else:
            self.send_error_packet(
                self.user_id, self.session_id, PacketErrorCodes.UNKOWN_MSG_TYPE
            )

    def start_process_packet(self, packet: Packet):
        self._pool.submit(self._process_packet, packet)

    def send_ack_packet(self):
        ack_packet = Packet(
            0, self.user_id, self.session_id, "OK".encode(), MessageType.ACK_SERVER, 0
        )
        queue_packets.send_packets.put(ack_packet)

    @staticmethod
    def send_error_packet(user_id: int, session_id: int, error_code: int):
        payload = str(error_code).encode()

        error_packet = Packet(
            id=0,
            user_id=user_id,
            session_id=session_id,
            payload=encrypt_payload(payload),
            msg_type=MessageType.ERROR_RESPONSE,
            flags=0,
        )
        queue_packets.send_packets.put(error_packet)
