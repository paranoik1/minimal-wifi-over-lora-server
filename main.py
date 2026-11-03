import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler

import serial
from core.packet import MessageType

from lora.managers import LoraReceiver, LoraSender
from lora.queue_packets import received_packets
from user_session import UserSession

logging.basicConfig(
    level=logging.DEBUG,
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
lora_900mghz_serial = serial.Serial("/dev/ttyUSB3", baudrate=115200)

lora_receiver = LoraReceiver(lora_900mghz_serial, lora_thread_pool)
lora_sender = LoraSender(lora_900mghz_serial, lora_thread_pool)

lora_receiver.start()
lora_sender.start()


def finish_user_session(user_id: UserID, session_id: SessionID):
    try:
        del user_session_map[user_id][session_id]
    except KeyError:
        logger.warning(f"UserSession с {user_id=} и {session_id=} не найден")


def get_user_session_object(user_id: UserID, session_id: SessionID, *, force_new: bool = False) -> UserSession:
    if user_id not in user_session_map:
        user_session_map[user_id] = {
            session_id: UserSession(sessions_thread_pool, user_id, session_id)
        }
        return user_session_map[user_id][session_id]

    if session_id not in user_session_map[user_id] or force_new:
        usr_session = UserSession(sessions_thread_pool, user_id, session_id)
        user_session_map[user_id][session_id] = usr_session
        return usr_session

    return user_session_map[user_id][session_id]


def main_loop():
    while True:
        pkt = received_packets.get()
        if pkt.calculate_crc8() != pkt.crc8:
            logger.debug(f"Получили поломанный пакет, пропускаем... {pkt}")
            continue

        logger.debug(f"Ваилдный пакет, начинаем обработку")

        # NOTE: по хорошему, лучше вынести проверку msg_type (например, создать методы в Packet классе)
        if pkt.msg_type == MessageType.FINISH_SESSION:
            logger.info(f"Получен пакет FINISH_SESSION (user_id={pkt.user_id} session_id={pkt.session_id}), отключаем сессию")
            finish_user_session(pkt.user_id, pkt.session_id)
            continue

        is_new_session = pkt.msg_type == MessageType.MSG_REQUEST
        user_session = get_user_session_object(
            pkt.user_id, pkt.session_id, force_new=is_new_session
        )
        if user_session.check_duplicate(pkt):
            logger.info(f"Получен дубликат, пропускаем... {pkt}")
            continue

        user_session.start_process_packet(pkt)

        user_session.send_ack_packet()



try:
    main_loop()
finally:
    print("Отрубаем потоки...")
    lora_thread_pool.shutdown()
    sessions_thread_pool.shutdown()
