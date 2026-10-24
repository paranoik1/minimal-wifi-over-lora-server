import serial

# Открываем порт UART в Linux (путь зависит от модели и настроек Orange Pi)
ser = serial.Serial('/dev/ttyS5', baudrate=115200)

while True:
    byte = ser.read()
    if byte:
        char = byte.decode()
        print(char)
        ser.write(f"I receive: {char}".encode())
