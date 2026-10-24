import serial

# Открываем порт UART в Linux (путь зависит от модели и настроек Orange Pi)
ser = serial.Serial('/dev/ttyS5', baudrate=115200)
MESSAGE_SIZE = 255


def receive_packet():
    byte = ser.read(MESSAGE_SIZE)
    if byte:
        return byte.decode()


def send_packet(packet: bytes):
    ser.write(packet)
