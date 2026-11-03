from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable
import logging

import serial

import lora.queue_packets as queue_packets
from core.packet import Packet


class _LoraBase:
    LOGGER_NAME = "lora_base"

    def __init__(self, serial: serial.Serial, thread_pool: ThreadPoolExecutor):
        self._pool = thread_pool
        self._serial = serial
        self._lora_future: Future | None = None
        self.logger = logging.getLogger(self.LOGGER_NAME)

    def _start(self, fn: Callable, *args, **kwargs):
        if self._lora_future:
            raise RuntimeError(
                "Нельзя дважды вызвать start, пока существует запущенный Future для обработки"
            )

        self._lora_future = self._pool.submit(fn, *args, **kwargs)


class LoraReceiver(_LoraBase):
    LOGGER_NAME = "lora_receiver"

    metadata_size = Packet.get_size_metadata_packet()
    after_payload_size = Packet.get_size_bytes_after_payload()

    def _receive_packet(self) -> Packet:
        metadata_size = self.metadata_size
        pkt_metadata = self._serial.read(metadata_size)

        length_payload = Packet.unpack_length_payload(pkt_metadata)
        other = self._serial.read(length_payload + self.after_payload_size)
        packet_raw = pkt_metadata + other

        return Packet.from_bytes(packet_raw)

    def _loop_receive_packets(self):
        while True:
            packet = self._receive_packet()
            queue_packets.received_packets.put(packet)

    def start(self):
        self._start(self._loop_receive_packets)


class LoraSender(_LoraBase):
    LOGGER_NAME = "lora_sender"
    MAX_PACKET_SIZE = 240

    def _loop_send_packets_from_queue(self):
        while True:
            packet = queue_packets.send_packets.get()
            packet_raw = packet.to_bytes()
            if len(packet_raw) > self.MAX_PACKET_SIZE:
                raise ValueError(
                    f"Размер пакета не должен быть больше {self.MAX_PACKET_SIZE} байт. Размер пакета: {len(packet_raw)}, пакет: {packet}"
                )
            bytes_written = self._serial.write(packet_raw)
            # self._serial.flush()
            self.logger.info(f"Записано {bytes_written} байт")

    def start(self):
        self._start(self._loop_send_packets_from_queue)
