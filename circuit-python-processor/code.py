import usb_hid
import board
import time
import busio
import os
import time
import ssl
import wifi
import socketpool
import adafruit_requests
import json

from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS

# Set up a keyboard device.
kbd = Keyboard(usb_hid.devices)
keyboard_uart = busio.UART(board.GP0, board.GP1, baudrate=115200)
layout = KeyboardLayoutUS(kbd)

API_LINK = "https://api.openai.com/v1/engines/chat/completions"
TEST_TEXT = "This is a test text to be sent to the computer in order to see the typing speed and lag."
SSID = os.getenv("WIFI_SSID")
PASSWORD = os.getenv("WIFI_PASSWORD")
API_KEY = os.getenv("OPENAI_API_KEY")
if API_KEY is None:
    print("API KEY not found")

wifi.radio.connect(SSID, PASSWORD)
print("IP address is", wifi.radio.ipv4_address)

def iter_lines(resp):
    partial_line = []
    for c in resp.iter_content():
        if c == b'\n':
            yield (b"".join(partial_line)).decode('utf-8')
            del partial_line[:]
        else:
            partial_line.append(c)
    if partial_line:
        yield (b"".join(partial_line)).decode('utf-8')

def call_chatgpt(text):
    pool = socketpool.SocketPool(wifi.radio)
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    full_prompt = [{"role": "user", "content": text},]

    with requests.post("https://api.openai.com/v1/chat/completions",
        json={"model": "gpt-3.5-turbo", "messages": full_prompt, "stream": True},
        headers={
        "Authorization": f"Bearer {API_KEY}",
        },
        ) as response:
            if response.status_code == 200:
                for line in iter_lines(response):
                    if line.startswith("data: [DONE]"):
                        break
                    if line.startswith("data: "):
                        data = json.loads(line[5:])
                        word = data.get('choices')[0].get('delta').get('content')
                        if word is not None:
                            layout.write(word)
            else:
                print("Error: ", response.status_code, response.content)

i = 0
pressed = False
def read_uart(current_char, pressed):
    if keyboard_uart.in_waiting >= 13:
        try:
            data = keyboard_uart.read(keyboard_uart.in_waiting)
            print(data)
            if not pressed:
                pressed = True
                layout.write(TEST_TEXT[i % len(TEST_TEXT)])
            else:
                i += 1
                pressed = False
        except:
            pass

def read_from_serial_monitor():
    if serial_monitor.in_waiting:
        data = serial_monitor.read(serial_monitor.in_waiting)
        return data.decode("utf-8")
    return None

# call_chatgpt("Test")