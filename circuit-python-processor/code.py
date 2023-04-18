import usb_hid
import board
import busio
import os
import time
import ssl
import wifi
import socketpool
import adafruit_requests
import json
import usb_cdc

from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
from hid import HID_KEYCODE_TO_ASCII, MODIFIER_LIST
from digitalio import DigitalInOut, Direction

# Setup keybord UART communication
keyboard_uart = busio.UART(board.GP0, board.GP1, baudrate=115200)

# Setup USB monitor communication
serial_monitor = usb_cdc.console

# Set up a keyboard device.
kbd = Keyboard(usb_hid.devices)
layout = KeyboardLayoutUS(kbd)

LED = DigitalInOut(board.LED)
LED.direction = Direction.OUTPUT
API_LINK = "https://api.openai.com/v1/engines/chat/completions"
TEST_TEXT = "This is a test text to be sent to the computer in order to see the typing speed and lag."
SSID = os.getenv("WIFI_SSID")
PASSWORD = os.getenv("WIFI_PASSWORD")
API_KEY = os.getenv("OPENAI_API_KEY")
if API_KEY is None:
    print("API KEY not found")

time.sleep(1)


def connect_to_wifi():
    print("Available networks:")
    for network in wifi.radio.start_scanning_networks():
        print("\t%s\t\tRSSI: %d\tChannel: %d" % (str(network.ssid, "utf-8"), network.rssi, network.channel))
    wifi.radio.stop_scanning_networks()
    while wifi.radio.ipv4_address is None:
        try:
            wifi.radio.connect(SSID, PASSWORD)
        except:
            print("Couldn't connect to WiFi")
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
    text_response = ""
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
                            print(word, end="")
                            text_response += word
                            try:
                                layout.write(word)
                            except:
                                pass
            else:
                print("Error: ", response.status_code, response.content)
    return text_response

def read_uart(current_uart_data):
    if keyboard_uart.in_waiting:
        to_read = keyboard_uart.in_waiting
        bytes = keyboard_uart.read(to_read)
        current_uart_data.extend(bytes)

def read_from_serial_monitor():
    in_data = bytearray()
    try:
        while True:
            if serial_monitor.in_waiting > 0:
                byte = serial_monitor.read(1)
                if byte == b'\n':
                    return in_data.decode('utf-8')
                else:
                    in_data.append(byte[0]) 
                    if len(in_data) == 129:
                        in_data = in_data[128] + in_data[0:127]
    except Exception as e:
        print(e)


#TODO: Use https://stackoverflow.com/a/75416309 to only retain last 5 answers
# so that we don't waste lots of tokens
# session_chats = []
# current_prompt = read_from_serial_monitor()
# while True:
#     current_response = call_chatgpt(current_prompt)
#     current_prompt += current_response
#     current_prompt += read_from_serial_monitor()

def list_diff(l1, l2):
    return [x for x in l1 if x not in l2]

if __name__ == '__main__':
    connect_to_wifi()
    current_uart_data = bytearray()
    last_pressed_keycodes = []
    last_pressed_characters = []
    current_prompt = ''
    listening_for_prompt = False
    call_api = False
    LED.value = False
    while True:
        read_uart(current_uart_data)
        if len(current_uart_data) > 0 and current_uart_data[-1] == 255:
            keycodes = []
            modifiers = []
            characters = []

            L_modifiers_mask = current_uart_data[1] & 0b00001111
            R_modifiers_mask = (current_uart_data[1] & 0b11110000) >> 4
            L_modifiers = [MODIFIER_LIST[i] for i in range(len(MODIFIER_LIST)) if (L_modifiers_mask >> i) & 1]
            R_modifiers = [MODIFIER_LIST[i] for i in range(len(MODIFIER_LIST)) if (R_modifiers_mask >> i) & 1]
            modifiers.extend(L_modifiers)
            modifiers.extend(R_modifiers)
            keycodes.extend(modifiers)

            for i in range(3, 8):
                character = HID_KEYCODE_TO_ASCII[current_uart_data[i]][0]
                if character != 0:
                    characters.append(character)
                    keycodes.append(layout.keycodes(character)[0])

            if keycodes == [Keycode.CONTROL, Keycode.ALT, Keycode.ENTER]:
                if listening_for_prompt == False:
                    listening_for_prompt = True
                    LED.value = True
                else:
                    listening_for_prompt = False
                    LED.value = False
                    print(current_prompt)
                    call_api = True

            pressed_keycodes = list_diff(keycodes, last_pressed_keycodes)
            released_keycodes = list_diff(last_pressed_keycodes, keycodes)
            pressed_characters = list_diff(characters, last_pressed_characters)
            released_characters = list_diff(last_pressed_characters, characters)
            for keycode in pressed_keycodes:
                kbd.press(keycode)
            for keycode in released_keycodes:
                kbd.release(keycode)

            if listening_for_prompt:
                if(len(pressed_characters) > 0):
                    # Exit if escape is pressed
                    if pressed_characters[0] == '\x1b':
                        print("Exiting listening mode")
                        current_prompt = ""
                        listening_for_prompt = False
                        LED.value = False
                    elif pressed_characters[0] == '\x08':
                        current_prompt = current_prompt[:-1]
                    else:
                        current_prompt += pressed_characters[0]

            last_pressed_keycodes = keycodes
            last_pressed_characters = characters

            if call_api == True:
                call_api = False
                call_chatgpt(current_prompt)
                current_prompt = ""

            current_uart_data = bytearray()