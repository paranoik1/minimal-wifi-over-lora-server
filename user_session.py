import logging
import struct

import threading
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import lora.queue_packets as queue_packets
from core.compress import default_compressor, markdown_compressor
from core.packet import MessageType, Packet, PacketErrorCodes, PacketFlags
from core.security import decrypt_payload, encrypt_payload
from handlers import get_all_handlers, HandlerPayloadError


class UserSession:
    MAX_CHUNK_PAYLOAD_SIZE = 230

    def __init__(self, thread_pool: ThreadPoolExecutor, user_id: int, session_id: int):
        self.user_id = user_id
        self.session_id = session_id
        self._pool = thread_pool
        self._logger = logging.getLogger(f"user_session   {user_id=} {session_id=}")

        self._lock_sended_pkts = threading.Lock()
        self._lock_received_pkts_hashes = threading.Lock()

        self._received_packets_hashes: set[bytes] = set()
        # Пакеты добавляются по очереди => отсортированный список
        self._sended_packets: list[Packet] = [] 

    def check_duplicate(self, packet: Packet) -> bool:
        """
        True - если пакет уже ранее был получен данным UserSession, иначе False
        """
        digest_packet = sha256(packet.to_bytes()).digest()
        with self._lock_received_pkts_hashes:
            return digest_packet in self._received_packets_hashes 

    def _call_handler(self, payload: str, pkt: Packet) -> str:
        """Возвращает полученный payload от подходящего handler"""
        # TODO: в будущем handler должен будет возвращать информацию о response
        # К примеру, Тип: чтобы определять, какой compressor стоит использовать для него
        for check, handler in get_all_handlers().items():
            if check(payload):
                return handler(payload)

        raise ValueError(f"Не найден нужный handler под данный payload: {payload}")

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
        max_chunk_size = self.MAX_CHUNK_PAYLOAD_SIZE
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

    def __process_msg_request_packet(self, payload: bytes, packet: Packet):
        try:
            payload_str = payload.decode()
            response_text = self._call_handler(payload_str, packet)
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
        except:
            self._logger.exception("Произошла непредвиденная ошибка во время обработки пакета")
            return

        response_packets = self._create_response_packets(
            packet, response_text.encode()
        )
        for pkt in response_packets:
            queue_packets.send_packets.put(pkt)
            with self._lock_sended_pkts:
                self._sended_packets.append(pkt)

    def __process_received_packets_report(self, payload: bytes, packet: Packet):
        # Структура такого пакета - если это первая часть отчета (отчет может быть разбит на несколько пакетов, если информация не влезла в один payload), то первые 2 байта - max_pkt_id, иначе это поле опускается
        # Остальной payload - известные непришедшие пакеты
        _index = 2 if packet.pkt_id == 0 else 0
        missing_packets_raw = payload[_index:].decode()
        pkts_range = missing_packets_raw.split(",")

        def check_sended_and_send_pkt(pkt_id: int):
            """
            Функция для безопасной проверки того, был ли отправлен пакет с pkt_id

            Если нет, то не отправляем пакет по новой, так как он еще не был отправлен основным потоком (`_process_msg_request`)

            Если да - получаем этот пакет из `self._sended_packets` и отправляем повторно 
            """
            with self._lock_sended_pkts:
                # Пакеты добавляются по очереди => отсортированный список
                if pkt_id < len(self._sended_packets): # пакет с этим id еще не был отправлен
                    packet = self._sended_packets[pkt_id]
                    queue_packets.send_packets.put_nowait(packet)

        for pkt_id_or_range in pkts_range:
            if "-" not in pkt_id_or_range:
                try:
                    pkt_id = int(pkt_id_or_range)
                except ValueError:
                    self._logger.error(f"Было получено не числовое значение - pkt_id={pkt_id_or_range}")
                    continue

                check_sended_and_send_pkt(pkt_id)
                continue
            
            pkt_range = pkt_id_or_range
            start_id_raw, finish_id_raw = pkt_range.split("-")
            try:
                start_id = int(start_id_raw)
                finish_id = int(finish_id_raw)
            except ValueError:
                self._logger.error(f"Были получены не числовые данные - {start_id=}, {finish_id=}")
                continue

            for pkt_id in range(start_id, finish_id + 1):
                check_sended_and_send_pkt(pkt_id)

        # если это часть пакета REPORT_RECEIVED_PACKETS => мы уже отправляли пакеты выше max_pkt_id => пропускаем этот шаг 
        if packet.pkt_id != 0:
            return
        
        # Проверяем, отправляли ли мы пакеты, которые стоят выше max_pkt_id
        # Если нет, пропускаем шаг
        # В ином случае отправляем все выше стоящие пакеты по новой
        max_pkt_id = struct.unpack(
            ">H", payload[:2]
        )[0]
        with self._lock_sended_pkts:
            if max_pkt_id >= len(self._sended_packets):
                return
            # пакет с pkt_id = max_pkt_id пропускаем (добавляя + 1 к индексу) 
            repeat_pkts = self._sended_packets[max_pkt_id + 1:]
        
        for repeat_pkt in repeat_pkts:
            queue_packets.send_packets.put_nowait(repeat_pkt)

    def _process_packet(self, packet: Packet):
        self._logger.info(f"Начинаем обработку пакета: {packet}")

        pkt_raw_hash = sha256(packet.to_bytes()).digest()
        with self._lock_received_pkts_hashes:
            self._received_packets_hashes.add(pkt_raw_hash)

        payload = decrypt_payload(packet.payload)
        if packet.flags & PacketFlags.FLAG_COMPRESSED:
            payload = default_compressor.decompress(payload)

        if packet.msg_type == MessageType.MSG_REQUEST:
            return self.__process_msg_request_packet(payload, packet)
        
        if packet.msg_type == MessageType.RECEIVED_PACKETS_REPORT:
            return self.__process_received_packets_report(payload, packet)

        self.send_error_packet(
            self.user_id, self.session_id, PacketErrorCodes.UNKOWN_MSG_TYPE
        )

    def start_process_packet(self, packet: Packet):
        self._pool.submit(self._process_packet, packet)

    def send_ack_packet(self):
        payload = encrypt_payload("OK".encode())
        ack_packet = Packet(
            0, self.user_id, self.session_id, payload, 
            MessageType.ACK_SERVER, 0
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
    report = struct.pack(">H", 7) + b"1,3-5"
    pkt0 = Packet(0, 0, 0, report, MessageType.RECEIVED_PACKETS_REPORT, 0)
    pkt1 = Packet(1, 0, 0, b"6", MessageType.RECEIVED_PACKETS_REPORT, 0)
    session = UserSession(None, 0, 0) # type: ignore
    for i in range(0, 10):
        pkt = Packet(i, 0, 0, b"Hello", MessageType.RESPONSE_SERVER, 0)
        session._sended_packets.append(pkt)
        
    session._process_packet(pkt0)
    session._process_packet(pkt1)

