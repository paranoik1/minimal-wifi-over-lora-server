import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import lora.queue_packets as queue_packets
from core.compress import default_compressor, markdown_compressor
from core.packet import MessageType, Packet, PacketErrorCodes, PacketFlags
from core.security import decrypt_payload, encrypt_payload
from handlers import get_all_handlers, HandlerPayloadError


class UserSession:
    MAX_CHUNK_SIZE = 230

    def __init__(self, thread_pool: ThreadPoolExecutor, user_id: int, session_id: int):
        self.user_id = user_id
        self.session_id = session_id
        self._pool = thread_pool
        self._logger = logging.getLogger(f"user_session   {user_id=} {session_id=}")

        self._lock = threading.Lock()

        self._received_packets: list[Packet] = []
        self._sended_packets: list[Packet] = []

    def _call_handler(self, payload: str, pkt: Packet) -> str:
        """Возвращает полученный payload от подходящего handler"""
        # TODO: в будущем handler должен будет возвращать информацию о response
        # К примеру, Тип: чтобы определять, какой compressor стоит использовать для него
        for check, handler in get_all_handlers().items():
            if check(payload):
                return handler(payload)

        raise ValueError(f"Не найден нужный handler под данный payload: {payload[:5]}")
    
    def _chunking(self, response: bytes, postprocess: Callable[[bytes], bytes]):
        max_chunk_size = self.MAX_CHUNK_SIZE

        compressed_chunks: list[bytes] = []
        for i in range(0, len(response), max_chunk_size):
            # если сущесвутет весь сжатый response - не занимаемся повторным сжатием чанков
            # и добавляем чанк в compressed_chunks как есть
            # в противном случае - сжимаем чанк и добавляем в список compressed_chunks
            chunk_raw = response[i:i+max_chunk_size]
            chunk = postprocess(chunk_raw)

            compressed_chunks.append(chunk)
        return compressed_chunks
    
    def _create_response_packets(
        self, request_packet: Packet, response: bytes
    ) -> list[Packet]:
        # Проверяем флаг FLAG_RESPONSE_NEDDED_FULL_PAYLOAD_COMPRESSED
        # если он активен, то сжимаем весь response сразу
        # иначе - compressed_response = None, что свидетельсвует о том, что флаг не активен
        if (
            request_packet.flags
            & PacketFlags.FLAG_RESPONSE_NEDDED_FULL_PAYLOAD_COMPRESSED
        ):
            compressed_response = markdown_compressor.compress(response)
            postprocess_chunks = lambda chunk: chunk
        else:
            compressed_response = None
            postprocess_chunks = lambda chunk: markdown_compressor.compress(chunk)

        compressed_chunks: list[bytes] = self._chunking(
            response = compressed_response or response,
            postprocess = postprocess_chunks
        )
        max_chunk_size = self.MAX_CHUNK_SIZE

        packets: list[Packet] = []
        pkt_current_id = 0
        chunk_idx = 0
        # формируем пакеты на основе полученных чанков
        while chunk_idx <= len(compressed_chunks):
            pkt_flags = PacketFlags.FLAG_COMPRESSED

            # проверяем, является ли это последним чанком
            # если да - устанавливаем FLAG_FINAL_PACKET
            # в ином случае задаем next_chunk, дабы объединить их, чтобы отправить
            # больше информации за раз
            if chunk_idx >= len(compressed_chunks):
                pkt_flags |= PacketFlags.FLAG_FINAL_PACKET

            payload = compressed_chunks[chunk_idx]

            if len(payload) > max_chunk_size:
                raise RuntimeError(f"Каким то образом chunk стал больше по размеру, чем {max_chunk_size} байт...")
            elif len(payload) == max_chunk_size:
                chunk_idx += 1
            else:
                while len(payload) < max_chunk_size:
                    if chunk_idx >= len(compressed_chunks):
                        pkt_flags |= PacketFlags.FLAG_FINAL_PACKET
                        break

                    chunk_idx += 1
                    next_chunk = compressed_chunks[chunk_idx]
                    
                    if len(next_chunk) + len(payload) > max_chunk_size:
                        break

                    payload += next_chunk

            packet = Packet(
                pkt_current_id,
                self.user_id,
                self.session_id,
                payload,
                MessageType.RESPONSE_SERVER,
                pkt_flags,
            )
            pkt_current_id += 1

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
            except HandlerPayloadError as ex:
                self._logger.error(f"Ошибка во время выполнения handler: {ex}")
                self.send_error_packet(
                    self.user_id,
                    self.session_id,
                    PacketErrorCodes.FAILED_CALL_HANDLER_PAYLOAD,
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
            # TODO: реализовать
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


if __name__ == '__main__':
    with open("response_test.md", "rb") as fp:
        response = fp.read()

    # compressed1 = markdown_compressor.compress(response[:230])
    # compressed2 = markdown_compressor.compress(response[230:245])
    # decoded = markdown_compressor.decompress_frames(compressed1 + compressed2).decode("utf-8", errors="replace")
    # print()
    UserSession(None, 1, 2)._create_response_packets(
        Packet(0, 1, 1, "url".encode(), MessageType.RESPONSE_SERVER, PacketFlags.FLAG_RESPONSE_NEDDED_FULL_PAYLOAD_COMPRESSED),
        response
    )
