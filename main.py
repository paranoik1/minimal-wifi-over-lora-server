import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler

import serial

from lora.managers import LoraReceiver, LoraSender
from lora.queue_packets import received_packets
from user_session import UserSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(
            "journal.log",
            encoding="utf-8",
            backupCount=5,
            maxBytes=5242880 * 3,  # 15МБ
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


UserID = int
SessionID = int

user_session_map: dict[UserID, dict[SessionID, UserSession]] = {}


lora_thread_pool = ThreadPoolExecutor(4, "LoRa_")
sessions_thread_pool = ThreadPoolExecutor(20, "UserSession_")


# Открываем порт UART в Linux
lora_900mghz_serial = serial.Serial("/dev/ttyUSB1", baudrate=115200)

lora_receiver = LoraReceiver(lora_900mghz_serial, lora_thread_pool)
lora_sender = LoraSender(lora_900mghz_serial, lora_thread_pool)

lora_receiver.start()
lora_sender.start()


def get_user_session_object(user_id: UserID, session_id: SessionID) -> UserSession:
    if user_id not in user_session_map:
        user_session_map[user_id] = {
            session_id: UserSession(sessions_thread_pool, user_id, session_id)
        }
        return user_session_map[user_id][session_id]

    if session_id not in user_session_map[user_id]:
        usr_session = UserSession(sessions_thread_pool, user_id, session_id)
        user_session_map[user_id][session_id] = usr_session
        return usr_session

    return user_session_map[user_id][session_id]


while True:
    pkt = received_packets.get()
    if pkt.calculate_crc8() != pkt.crc8:
        # NOTE: если контрольная сумма пакета не верная (не совпадает с вичсленной)
        # то какая гарантия, что мы получим верные user_id и session_id?
        # как тогда быть? Отправлять широковещательный пакет с timestamp?
        # а как пользователь на стороне определит, что данный пакет относится именно к его запросу?
        # UserSession.send_error_packet(pkt.user_id, pkt.session_id, PacketErrorCodes.FAILED_CHECK_SUM)
        continue

    user_session = get_user_session_object(pkt.user_id, pkt.session_id)
    user_session.start_process_packet(pkt)

    user_session.send_ack_packet()
