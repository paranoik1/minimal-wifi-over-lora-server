from queue import Queue

from core.packet import Packet

received_packets: Queue[Packet] = Queue()
send_packets: Queue[Packet] = Queue()
