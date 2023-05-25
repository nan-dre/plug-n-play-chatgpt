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
import rotaryio
import displayio
import adafruit_ili9341
import terminalio
import analogio
import gc
from adafruit_display_text import label, wrap_text_to_pixels


from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
from hid import HID_KEYCODE_TO_ASCII, L_MODIFIER_LIST, R_MODIFIER_LIST, SHIFTED_CHARACTERS, DECODE_DIACRITICS
from digitalio import DigitalInOut, Direction, Pull

# Setup keybord UART communication
keyboard_uart = busio.UART(board.GP0, board.GP1, baudrate=115200)

LED = DigitalInOut(board.LED)
LED.direction = Direction.OUTPUT

# Setup USB monitor communication
serial_monitor = usb_cdc.console
serial_monitor.timeout = None


# Set up a keyboard device.
connected_to_pc = True
try:
    kbd = Keyboard(usb_hid.devices)
    layout = KeyboardLayoutUS(kbd)
except:
    connected_to_pc = False

# Set up a rotary encoder
encoder = rotaryio.IncrementalEncoder(board.GP17, board.GP16)
button = DigitalInOut(board.GP18)
button.direction = Direction.INPUT
button.pull = Pull.UP

DIRECTIONS = ["up", "down", "left", "right", "center"]

# Set up display
DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 320
SCALE_FACTOR = 2
CHARACTER_LIMIT = 130
displayio.release_displays()
spi = busio.SPI(clock=board.GP10, MOSI=board.GP11)
display_bus = displayio.FourWire(spi, command=board.GP12, chip_select=board.GP13, reset=board.GP14)
display = adafruit_ili9341.ILI9341(display_bus, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, rotation=180)
current_display_prompt = ""


API_LINK = "https://api.openai.com/v1/engines/chat/completions"
SSID = os.getenv("WIFI_SSID")
PASSWORD = os.getenv("WIFI_PASSWORD")
API_KEY = os.getenv("OPENAI_API_KEY")
if API_KEY is None:
    print("API KEY not found")

class Menu:
    options = ["Simple prompt", "Translate", "Refactor", "Document", "Correct"]
    prompts = [
        "",
        "Translate this text to english: ",
        "Refactor this code, don't write any other comments: ",
        "Document this code, don't write any other comments: ",
        "Correct any mistakes you find in this text: "
    ]
    current_option = 0

    def next_option(self):
        self.current_option = (self.current_option + 1) % len(self.options)
    
    def previous_option(self):
        self.current_option = (self.current_option - 1) % len(self.options)

def initialize_display():
    splash = displayio.Group()
    display.show(splash)

    # Draw a smaller inner rectangle
    inner_bitmap = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
    inner_palette = displayio.Palette(1)
    inner_palette[0] = 0xFFFFFF  # Black
    inner_sprite = displayio.TileGrid(inner_bitmap, pixel_shader=inner_palette, x=0, y=0)
    splash.append(inner_sprite)

    # Draw a label

    text_group = displayio.Group(scale=SCALE_FACTOR, x=0, y=20)
    text_area = label.Label(terminalio.FONT, text="", color=0x000000, )
    text_group.append(text_area)  # Subgroup for text scaling
    splash.append(text_group)
    return text_area

def display_text(label, text):
    wrapped_text = "\n".join(wrap_text_to_pixels(text, max_width=DISPLAY_WIDTH/SCALE_FACTOR, font=terminalio.FONT))[:CHARACTER_LIMIT]
    label.text = wrapped_text
    gc.collect()

def display_list(label, options, current_option):
    displayed_options = options.copy()
    displayed_options[current_option] = options[current_option] + " <-"
    wrapped_text = "\n".join(displayed_options)
    label.text = wrapped_text
    gc.collect()

def connect_to_wifi():
    tries = 0
    wifi.radio.start_scanning_networks()
    wifi.radio.stop_scanning_networks()
    while wifi.radio.ipv4_address is None and tries < 5:
        try:
            wifi.radio.connect(SSID, PASSWORD)
        except:
            tries += 1
            print("Couldn't connect to WiFi")
    if tries >= 5:
        print("Maximum wifi tries reached")
        return False
    else:
        print("IP address is", wifi.radio.ipv4_address)
        return True

def remove_diacritics(word):
    for diacritic in DECODE_DIACRITICS:
        word = word.replace(diacritic, DECODE_DIACRITICS[diacritic])
    return word

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


def call_chatgpt(text, requests, label):
    text_response = ""
    full_prompt = [{"role": "user", "content": text},]
    global current_display_prompt
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
                        text_response += word
                        word = remove_diacritics(word)
                        current_display_prompt += word
                        if(len(current_display_prompt) > CHARACTER_LIMIT):
                            display_text(label, current_display_prompt)
                            current_display_prompt = ""
                        print(word, end="")
                        if connected_to_pc:
                            try:
                                layout.write(word)
                            except:
                                pass
        else:
            print("Error: ", response.status_code, response.content)
    display_text(label, current_display_prompt)
    current_display_prompt = ""
    gc.collect()
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
        character = HID_KEYCODE_TO_ASCII[packet[i]][0]
        if character != 0:
            characters.append(character)
        keycodes.append(packet[i])

    return keycodes, characters


def process_keycodes(keycodes, characters, current_prompt, listening_for_prompt, LED, call_api):
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

    if connected_to_pc:
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
                shifted_character = SHIFTED_CHARACTERS.get(pressed_characters[0])
                if Keycode.SHIFT in keycodes and shifted_character is not None:
                        current_prompt += shifted_character
                else:
                    current_prompt += pressed_characters[0]

    return listening_for_prompt, call_api, current_prompt, keycodes, characters


if __name__ == '__main__':
    if not connect_to_wifi():
        exit()
    label = initialize_display()
    menu = Menu()
    pool = socketpool.SocketPool(wifi.radio)
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    current_uart_data = bytearray()
    current_serial_data = ''
    last_pressed_keycodes = []
    last_pressed_characters = []
    responses = []
    current_prompt = ''
    listening_for_prompt = False
    viewing_prompt = False
    call_api = False
    LED.value = False
    last_position = 0
    button_state = None
    option_selected = True
    typing = True
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
                    call_api,
                )
                last_pressed_keycodes = keycodes
                last_pressed_characters = characters
                typing = True
                if all(i == 0 for i in keycodes):
                    typing = False

                if call_api == True and not typing:
                    call_api = False
                    current_prompt = menu.prompts[menu.current_option] + current_prompt
                    print(current_prompt)
                    display_text(label, current_prompt)
                    viewing_prompt = True
                    listening_for_serial = False
                    current_prompt += call_chatgpt(current_prompt, requests, label)

            current_uart_data = bytearray()


        # if not typing:
        exception, current_serial_data = read_from_serial_monitor()
        if len(current_serial_data) > 0 and exception == None:
            print("Serial data: " + current_serial_data)
            if listening_for_prompt:
                current_prompt += current_serial_data
                display_text(label, current_prompt)
                print(current_prompt)

        position = encoder.position
        if position != last_position:
            option_selected = True
            if position > last_position:
                menu.next_option()
            else:
                menu.previous_option()
        last_position = position
        if button.value and button_state is None:
            button_state = "pressed"
        if not button.value and button_state == "pressed":
            viewing_prompt = False
            button_state = None

        if not listening_for_prompt and not viewing_prompt and option_selected:
            option_selected = False
            display_list(label, menu.options, menu.current_option)