import serial

# Открываем порт UART в Linux (путь зависит от модели и настроек Orange Pi)
ser = serial.Serial('/dev/ttyUSB0', baudrate=115200)

while True:
    line = ser.readline()
    if line:
        print(line.decode())
