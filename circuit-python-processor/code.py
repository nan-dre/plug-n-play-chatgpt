import usb_hid
import board
import time
import busio

from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS

# Set up a keyboard device.
kbd = Keyboard(usb_hid.devices)
uart = busio.UART(board.GP0, board.GP1, baudrate=115200)
layout = KeyboardLayoutUS(kbd)

while True:
    if uart.in_waiting >= 13:
        try:
            data = uart.read(uart.in_waiting)
            print(data)
        except:
            pass