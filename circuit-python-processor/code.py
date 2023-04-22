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
from hid import HID_KEYCODE_TO_ASCII, L_MODIFIER_LIST, R_MODIFIER_LIST
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
SSID = os.getenv("WIFI_SSID")
PASSWORD = os.getenv("WIFI_PASSWORD")
API_KEY = os.getenv("OPENAI_API_KEY")
if API_KEY is None:
    print("API KEY not found")

def connect_to_wifi():
    tries = 0
    print("Available networks:")
    for network in wifi.radio.start_scanning_networks():
        print("\t%s\t\tRSSI: %d\tChannel: %d" %
              (str(network.ssid, "utf-8"), network.rssi, network.channel))
    wifi.radio.stop_scanning_networks()
    while wifi.radio.ipv4_address is None and tries < 3:
        try:
            wifi.radio.connect(SSID, PASSWORD)
        except:
            tries += 1
            print("Couldn't connect to WiFi")
    if tries >= 3:
        print("Maximum wifi tries reached")
        return False
    else:
        print("IP address is", wifi.radio.ipv4_address)
        return True


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


def call_chatgpt(text, requests):
    full_prompt = [{"role": "user", "content": text},]
    text_response = ""
    print("RESPONSE: ")
    with requests.post("https://api.openai.com/v1/chat/completions",
                       json={"model": "gpt-3.5-turbo",
                             "messages": full_prompt, "stream": True},
                       headers={
            "Authorization": f"Bearer {API_KEY}",
                           },
                       ) as response:
        if response.status_code == 200:
            for line in iter_lines(response):
                if line.startswith("data: [DONE]"):
                    break
                if line.startswith("data: "):
                    # If the user wants to end the prompt early
                    if keyboard_uart.in_waiting:
                        break
                    data = json.loads(line[5:])
                    word = data.get('choices')[0].get('delta').get('content')
                    if word is not None:
                        print(word, end="")
                        text_response += word
                        layout.write(word)
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
        while serial_monitor.in_waiting:
            byte = serial_monitor.read(1)
            if byte[0] == 255:
                return None, in_data.decode('utf-8')
            else:
                in_data.append(byte[0])
    except Exception as e:
        return e, in_data
    return None, in_data.decode('utf-8')


def list_diff(l1, l2):
    return [x for x in l1 if x not in l2]

def parse_packet(packet, modifier_pos, first_key_pos, last_key_pos):
    keycodes = []
    modifiers = []
    characters = []
    L_modifiers_mask = packet[modifier_pos] & 0b00001111
    R_modifiers_mask = (packet[modifier_pos] & 0b11110000) >> 4
    L_modifiers = [L_MODIFIER_LIST[i] for i in range(
        len(L_MODIFIER_LIST)) if (L_modifiers_mask >> i) & 1]
    R_modifiers = [R_MODIFIER_LIST[i] for i in range(
        len(R_MODIFIER_LIST)) if (R_modifiers_mask >> i) & 1]
    modifiers.extend(L_modifiers)
    modifiers.extend(R_modifiers)
    keycodes.extend(modifiers)

    for i in range(first_key_pos, last_key_pos + 1):
        character = HID_KEYCODE_TO_ASCII[packet[i]]
        if character != (0, 0):
            if Keycode.LEFT_SHIFT in modifiers or Keycode.RIGHT_SHIFT in modifiers:
                characters.append(character[1])
            else:
                characters.append(character[0])

        keycodes.append(packet[i])

    return keycodes, characters


def process_keycodes(keycodes, characters, current_prompt, listening_for_prompt, LED, kbd, call_api):
    if Keycode.GUI in keycodes and Keycode.ENTER in keycodes and Keycode.SHIFT not in keycodes:
        if listening_for_prompt == False:
            listening_for_prompt = True
            LED.value = True
        else:
            listening_for_prompt = False
            LED.value = False
            call_api = True

    pressed_keycodes = list_diff(keycodes, last_pressed_keycodes)
    released_keycodes = list_diff(last_pressed_keycodes, keycodes)
    pressed_characters = list_diff(characters, last_pressed_characters)
    # released_characters = list_diff(last_pressed_characters, characters)

    for keycode in pressed_keycodes:
        kbd.press(keycode)
    for keycode in released_keycodes:
        kbd.release(keycode)

    if listening_for_prompt:
        if (len(pressed_characters) > 0):
            # Exit if escape is pressed
            if pressed_characters[0] == '\x1b':
                print("Exiting listening mode and deleting history")
                current_prompt = ""
                listening_for_prompt = False
                LED.value = False
            elif pressed_characters[0] == '\x08':
                current_prompt = current_prompt[:-1]
            elif (Keycode.CONTROL or Keycode.ALT or Keycode.GUI) not in keycodes:
                if Keycode.SHIFT in keycodes:
                    current_prompt += pressed_characters[0].upper()
                else:
                    current_prompt += pressed_characters[0]

    return listening_for_prompt, call_api, current_prompt, keycodes, characters


if __name__ == '__main__':
    if not connect_to_wifi():
        exit()
    pool = socketpool.SocketPool(wifi.radio)
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    current_uart_data = bytearray()
    current_serial_data = ''
    last_pressed_keycodes = []
    last_pressed_characters = []
    current_prompt = ''
    listening_for_prompt = False
    call_api = False
    LED.value = False
    works = False
    while True:
        read_uart(current_uart_data)
        # Skip initial packet
        if len(current_uart_data) > 0 and current_uart_data[-1] == 255:
            packet_count = 0
            for i in range(len(current_uart_data)):
                if current_uart_data[i] == 255:
                    packet_count += 1
            packet_length = len(current_uart_data) // packet_count
            packets = [current_uart_data[i:i+packet_length]
                       for i in range(0, len(current_uart_data), packet_length)]
            for packet in packets:
                if len(packet) == 14:
                    keycodes, characters = parse_packet(packet, modifier_pos=1, first_key_pos=3, last_key_pos=7)
                elif len(packet) == 9:
                    keycodes, characters = parse_packet(packet, modifier_pos=0, first_key_pos=2, last_key_pos=6)
                else:
                    continue

                listening_for_prompt, call_api, current_prompt, keycodes, characters = process_keycodes(
                    keycodes,
                    characters,
                    current_prompt,
                    listening_for_prompt,
                    LED,
                    kbd,
                    call_api,
                )
                last_pressed_keycodes = keycodes
                last_pressed_characters = characters

                if call_api == True and all(i == 0 for i in keycodes):
                    call_api = False
                    print(current_prompt)
                    current_prompt += call_chatgpt(current_prompt, requests)

            current_uart_data = bytearray()

        exception, current_serial_data = read_from_serial_monitor()
        if len(current_serial_data) > 0 and listening_for_prompt:
            time.sleep(3)
            current_prompt += current_serial_data
            print(current_prompt)


