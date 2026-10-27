import logging
import threading
from concurrent.futures import ThreadPoolExecutor

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

    def _create_response_packets(
        self, request_packet: Packet, response: bytes
    ) -> list[Packet]:
        # Проверяем флаг FLAG_RESPONSE_NEDDED_FULL_PAYLOAD_COMPRESSED
        # если он активен, то сжимаем весь response сразу
        # иначе - compressed_response = None, что свидетельсвует о том, что флаг не активен
        original_response = response

        is_full_compress = False
        if (
            request_packet.flags
            & PacketFlags.FLAG_RESPONSE_NEDDED_FULL_PAYLOAD_COMPRESSED
        ):
            response = markdown_compressor.compress(response)
            is_full_compress = True

        compressed_chunks: list[bytes] = []
        max_chunk_size = self.MAX_CHUNK_SIZE
        for i in range(0, len(response), max_chunk_size):
            # если сущесвутет весь сжатый response - не занимаемся повторным сжатием чанков
            # и добавляем чанк в compressed_chunks как есть
            # в противном случае - сжимаем чанк и добавляем в список compressed_chunks
            chunk_raw = response[i:i+max_chunk_size]

            if not is_full_compress:
                # TODO: в будущем handler должен будет возвращать информацию о response
                # К примеру, Тип: чтобы определять, какой compressor стоит использовать для него
                chunk_raw = markdown_compressor.compress(chunk_raw)

            compressed_chunks.append(chunk_raw)

        packets: list[Packet] = []
        pkt_current_id = 0
        chunk_idx = 0
        # формируем пакеты на основе полученных чанков
        while chunk_idx <= len(compressed_chunks):
            pkt_flags = PacketFlags.FLAG_COMPRESSED

            # проверяем, является ли это последним чанком
            # если да - устанавливаем FLAG_FINAL_PACKET
            # В нижнем цикле есть повторяющееся условие - конкретно это нужно для обработки случая, когда последний чанк является последним и с максимальным размером payload (для одного пакета)
            if chunk_idx >= len(compressed_chunks):
                pkt_flags |= PacketFlags.FLAG_FINAL_PACKET

            payload = compressed_chunks[chunk_idx]

            if len(payload) > max_chunk_size:
                raise RuntimeError(f"Каким то образом chunk стал больше по размеру, чем {max_chunk_size} байт... Плохая функция, правь")
            elif len(payload) == max_chunk_size:
                # Вот для этого случая нужна верхняя проверка chunk_idx >= len(compressed_chunks)
                chunk_idx += 1
            else:
                # Цикл для добавления сжатых чанков в один payload (чтобы пакеты были заполнены максимально и за раз можно было отправить больше данных)
                # для разжатия таких данных на стороне клиента необходимо запустить ZstdStreamReader
                while len(payload) < max_chunk_size:
                    chunk_idx += 1

                    if chunk_idx >= len(compressed_chunks):
                        pkt_flags |= PacketFlags.FLAG_FINAL_PACKET
                        break

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
            if pkt_flags & PacketFlags.FLAG_FINAL_PACKET:
                break

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
