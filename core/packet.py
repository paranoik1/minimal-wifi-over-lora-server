import struct
from dataclasses import dataclass
from enum import Enum

PACKET_PAYLOAD_LENGTH = 240
USER_ID_BITS = 4
MSG_TYPE_BITS = 4
PACKET_ID_BITS = 2 * 8


class MessageType(Enum):
    # Типы сообщений от клиента
    MSG_REQUEST = 0
    # Тип сообщения, в котором клиент указывает, какие пакеты он ПОЛУЧИЛ
    # (клиент не знает об общем кол-ве пакетов)
    # идентификаторы пакетов перечисляются в payload
    RECEIVED_PACKETS_REPORT = 2

    RESPONSE_PACKET = 1
    # Нужен для того, чтобы клиент зафикисировал, сколько всего пакетов он должен был получить
    # и если он их не получил, то продолжать отправлять сообщения с типом RECEIVED_PACKETS_REPORT до тех пор, пока не получит FINAL_RESPONSE_PACKET и все недостающие пакеты
    FINAL_RESPONSE_PACKET = 3
    ERROR_RESPONSE = 4


# NOTE: А что насчет сессий? У каждого пользователя может быть много сессий и таким образом конкретная часть программы может определять, как обрабатывать данные и куда их потом класть (например, паралельное скачивание сайта и изображений на нем)
class Packet:
    max_user_id = 2**USER_ID_BITS
    max_pkt_id = 2**PACKET_ID_BITS

    def __init__(
        self,
        id: int,
        user_id: int,
        session_id: int,
        payload: bytes,
        msg_type: MessageType,
        *,
        flags: int = 0,
        crc8: int | None = None,
    ):
        if not (0 <= user_id < self.max_user_id):
            raise ValueError(
                f"user_id должен быть в диапазоне [0, {self.max_user_id}), "
                f"получено: {user_id}"
            )

        if not (0 <= id < self.max_pkt_id):
            raise ValueError(
                f"id должен быть в диапазоне [0, {self.max_pkt_id}), " f"получено: {id}"
            )

        if len(payload) > PACKET_PAYLOAD_LENGTH:
            raise ValueError(
                f"Размер Полезной нагрузки должен быть меньше {PACKET_PAYLOAD_LENGTH}"
            )

        # 4 бита - 2^4 значений (16 значений)
        self.user_id = user_id
        # 4 бита - 2^4 значений (16 значений)
        self.msg_type = msg_type
        # 2 байта - 2^16 значений (65536 значений)
        self.pkt_id = id
        # 4 бита
        self.session_id = session_id
        # 4 бита
        self.flags = flags
        # 1 байт - так как размер всего пакета составляет 255 байт (ограничение LoRa)
        # 1 байт это 8 бит, тоесть 1 байт может хранить 2^8 кол-во значений (256 значений)\
        # этого хватит, что бы хранить размер всей полезной нагрузки
        self.length_payload = len(payload)
        self.payload = payload
        # 1 байт
        self.crc8 = crc8 or self.calculate_crc8()

    def _to_bytes_without_crc8(self) -> bytes:
        # <B - unsigned char - 1 байт, в little-endian (в каком порядке размещать биты)
        header = struct.pack("<B", (self.user_id << 4) | self.msg_type.value)
        session_info = struct.pack("<B", (self.session_id << 4) | self.flags)
        # <H - unsigned short - 2 байта, в little-edian (на это указывает стрелочка <)
        pkt_id = struct.pack("<H", self.pkt_id)
        length_payload = struct.pack("<B", self.length_payload)

        return header + session_info + pkt_id + length_payload + self.payload

    @staticmethod
    def get_size_metadata_packet():
        return 5

    def to_bytes(self) -> bytes:
        crc8 = struct.pack("<B", self.crc8)

        return self._to_bytes_without_crc8() + crc8

    def __len__(self):
        return len(self.to_bytes())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Packet):
            return NotImplemented
        return self.calculate_crc8() == other.calculate_crc8()

    def __repr__(self) -> str:
        return (
            f"Packet(user_id={self.user_id}, msg_type={self.msg_type.name}, session_id={self.session_id}, "
            f"flags={self.flags:04b}, pkt_id={self.pkt_id}, len_payload={self.length_payload}, crc8={self.crc8:#02x})"
        )

    def check_crc8(self) -> bool:
        return self.calculate_crc8() == self.crc8

    def calculate_crc8(self):
        data = self._to_bytes_without_crc8()
        return self._crc8(data)

    @staticmethod
    def _crc8(data: bytes) -> int:
        """Реализация алгоритма CRC-8-CCITT (Poly=0x07, Init=0x00)"""
        crc = 0x00
        poly = 0x07  # первые 3 бита
        for byte in data:
            crc ^= byte  # ^ исключающее или (XOR)
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
                crc &= 0xFF  # Оставляем только 8 бит
        return crc

    @staticmethod
    def from_bytes(packet: bytes) -> "Packet":
        packet_metdata_length = Packet.get_size_metadata_packet()

        header, session_info, pkg_id, length_payload = struct.unpack(
            "<BBHB", packet[:packet_metdata_length]
        )
        user_id = header >> 4

        msg_type_raw = header & 0x0F

        try:
            msg_type = MessageType(msg_type_raw)
        except ValueError:
            raise ValueError(f"Неизвестный тип сообщения: {msg_type_raw}")

        session_id = session_info >> 4
        flags = session_info & 0x0F

        encrypted_payload = packet[
            packet_metdata_length : packet_metdata_length + length_payload
        ]
        # FIXME: если пакет придет не целостным, может возникнуть ошибка по его расшифровке и разжатии, поэтому необходимо сделать PacketRaw или вообще не создавать
        # decrypted_payload = Packet.decrypt_payload(encrypted_payload)
        crc8 = packet[packet_metdata_length + length_payload]

        return Packet(
            id=pkg_id,
            user_id=user_id,
            msg_type=msg_type,
            session_id=session_id,
            flags=flags,
            payload=encrypted_payload,
            crc8=crc8,
        )


class ResponseFactory:
    max_user_id = 2**USER_ID_BITS

    def __init__(self, user_id: int, session_id: int, full_payload: bytes):
        if user_id > self.max_user_id:
            raise ValueError(
                f"user_id The ordering of format characters may have an impact on size in native mode since padding is implicit. In standard mode, the user is responsible for inserting any desired padding. Note in the first pack call below that three NUL bytes were added after the packed '#' to align the following integer on a four-byte boundary. In this example, the output was produced on a little endian machine:не может быть больше {self.max_user_id}"
            )
        self.user_id = user_id
        self.session_id = session_id
        self.full_payload = full_payload

    def split_packets(self) -> list[Packet]:
        packets: list[Packet] = []
        counter = 0
        sep = PACKET_PAYLOAD_LENGTH
        for i in range(0, len(self.full_payload), sep):
            payload = self.full_payload[i : i + sep]
            pkt = Packet(
                counter,
                self.user_id,
                self.session_id,
                payload,
                MessageType.RESPONSE_PACKET,
            )
            packets.append(pkt)
            counter += 1

        packets[-1].msg_type = MessageType.FINAL_RESPONSE_PACKET
        return packets
