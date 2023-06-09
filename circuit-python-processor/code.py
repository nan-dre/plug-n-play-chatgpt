import usb_hid
import board
import busio
import os
import time
import ssl
import wifi
import socketpool
import ipaddress
import adafruit_requests
import json
import usb_cdc
import rotaryio
import displayio
import adafruit_ili9341
import terminalio
import gc
from adafruit_display_text import label, wrap_text_to_pixels
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
from hid import HID_KEYCODE_TO_ASCII, L_MODIFIER_LIST, R_MODIFIER_LIST, SHIFTED_CHARACTERS, DECODE_DIACRITICS
from digitalio import DigitalInOut, Direction, Pull

# Setup keybord UART communication
keyboard_uart = busio.UART(board.GP0, board.GP1, baudrate=115200)

# Setup onboard led
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
CHARACTER_LIMIT = 165
MAX_ROWS = 9
displayio.release_displays()
spi = busio.SPI(clock=board.GP10, MOSI=board.GP11)
display_bus = displayio.FourWire(
    spi, command=board.GP12, chip_select=board.GP13, reset=board.GP14)
display = adafruit_ili9341.ILI9341(
    display_bus, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, rotation=180)


API_LINK = "https://api.openai.com/v1/engines/chat/completions"
SSID = os.getenv("WIFI_SSID")
PASSWORD = os.getenv("WIFI_PASSWORD")
SSID_AUX = os.getenv("WIFI_SSID_AUX")
PASSWORD_AUX = os.getenv("WIFI_PASSWORD_AUX")
API_KEY = os.getenv("OPENAI_API_KEY")
if API_KEY is None:
    print("API KEY not found")

PORT = 5000
TIMEOUT = 7
BACKLOG = 2
MAXBUF = 512

DEBUGGING = False


class Result:
    def __init__(self, full_prompt, prompt_list):
        self.full_prompt = full_prompt
        self.prompt_list = prompt_list
        self.current_counter = len(prompt_list) - 1

    def display_next_prompt(self, label):
        self.current_counter += 1
        if self.current_counter >= len(self.prompt_list):
            self.current_counter = len(self.prompt_list) - 1
        display_text(label, self.prompt_list[self.current_counter])

    def display_previous_prompt(self, label):
        self.current_counter -= 1
        if self.current_counter < 0:
            self.current_counter = 0
        display_text(label, self.prompt_list[self.current_counter])


class Menu:
    options = ["Simple prompt", "Translate", "Refactor", "Document", "Correct"]
    prompts = [
        "",
        "Translate this text to english: ",
        "Refactor this code, don't write any other comments: ",
        "Add comments throughout this code, don't return any other text, only the commented code:",
        "Correct any mistakes you find in this text: "
    ]
    current_option = 0

    def next_option(self):
        self.current_option = (self.current_option + 1) % len(self.options)

    def previous_option(self):
        self.current_option = (self.current_option - 1) % len(self.options)

def initialize_tcp_server(pool):
    HOST = str(wifi.radio.ipv4_address)
    server = ipaddress.ip_address(pool.getaddrinfo(HOST, PORT)[0][4][0])
    print("Server ping", server, wifi.radio.ping(server), "ms")
    print("Create TCP Server socket", (HOST, PORT))
    s = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    s.settimeout(TIMEOUT)

    s.bind((HOST, PORT))
    s.listen(BACKLOG)
    print("Listening")
    return s

def accept_packet(socket):
    buf = bytearray(MAXBUF)
    print("Accepting connections")
    try:
        conn, addr = socket.accept()
        conn.settimeout(TIMEOUT)
        print("Accepted from", addr)

        size = conn.recv_into(buf, MAXBUF)
        print("Received", buf[:size], size, "bytes")
        print(str(buf, 'utf-8'))

        conn.close()
    except:
        print("Connection timed out")
    return buf


def initialize_display():
    splash = displayio.Group()
    display.show(splash)

    # Draw a smaller inner rectangle
    inner_bitmap = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
    inner_palette = displayio.Palette(1)
    inner_palette[0] = 0xFFFFFF  # Black
    inner_sprite = displayio.TileGrid(
        inner_bitmap, pixel_shader=inner_palette, x=0, y=0)
    splash.append(inner_sprite)

    # Draw a label

    text_group = displayio.Group(scale=SCALE_FACTOR, x=0, y=20)
    text_area = label.Label(terminalio.FONT, text="", color=0x000000)
    text_group.append(text_area)  # Subgroup for text scaling
    splash.append(text_group)
    return text_area


def display_text(label, text):
    # Limit characters, otherwise it can overflow memory
    text_list = wrap_text_to_pixels(text[:CHARACTER_LIMIT], max_width=DISPLAY_WIDTH / SCALE_FACTOR, font=terminalio.FONT)
    wrapped_text = "\n".join(text_list)
    label.text = wrapped_text
    gc.collect()


def display_list(label, options, current_option):
    displayed_options = options.copy()
    displayed_options[current_option] = options[current_option] + " <-"
    wrapped_text = "\n".join(displayed_options)
    label.text = wrapped_text
    gc.collect()


def connect_to_wifi(ssid, password):
    tries = 0
    ipv4 =  ipaddress.IPv4Address("192.168.43.164")
    netmask =  ipaddress.IPv4Address("255.255.255.0")
    gateway =  ipaddress.IPv4Address("192.168.43.150")
    wifi.radio.set_ipv4_address(ipv4=ipv4,netmask=netmask,gateway=gateway)
    while tries < 5:
        try:
            wifi.radio.connect(ssid, password)
            break
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


def call_chatgpt(text, requests, label, inside_IDE):
    text_response = ""
    full_prompt = [{"role": "user", "content": text},]
    current_display_prompt = ""
    segmented_display_prompt = []
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
                    word = data.get('choices')[0].get(
                        'delta').get('content')
                    if word is not None:
                        word = remove_diacritics(word)
                        text_response += word
                        current_display_prompt += word
                        if not inside_IDE:
                            wrapped_text = "\n".join(wrap_text_to_pixels(
                                current_display_prompt, max_width=DISPLAY_WIDTH/SCALE_FACTOR, font=terminalio.FONT))
                            if (wrapped_text.count("\n") > MAX_ROWS):
                                # Display the prompt, without the last word, in order to fill last row
                                # We will reuse it in the next screen
                                current_display_prompt = current_display_prompt[:-len(word)]
                                display_text(label, current_display_prompt)
                                segmented_display_prompt.append(
                                    current_display_prompt)
                                current_display_prompt = word
                        print(word, end="")
                        if connected_to_pc:
                            try:
                                layout.write(word)
                            except:
                                pass
        else:
            print("Error: ", response.status_code, response.content)
    if current_display_prompt != "" and not inside_IDE:
        segmented_display_prompt.append(current_display_prompt)
        display_text(label, current_display_prompt)
    gc.collect()
    result = Result(text_response, segmented_display_prompt)
    return result


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


def process_keycodes(keycodes, characters, current_prompt, listening_for_prompt, listening_for_clipboard, listening_notification, option_selected, inside_IDE, LED, call_api, label):
    if Keycode.GUI in keycodes and Keycode.ENTER in keycodes:
        if listening_for_prompt == False:
            # Without shift, don't retain context
            if Keycode.SHIFT not in keycodes:
                current_prompt = ""
            listening_for_prompt = True
            LED.value = True
        else:
            listening_for_prompt = False
            LED.value = False
            call_api = True

    if Keycode.CONTROL in keycodes and Keycode.ALT in keycodes and Keycode.TWO in keycodes and listening_for_clipboard == False:
        listening_for_clipboard = True

    if Keycode.CONTROL in keycodes and Keycode.ALT in keycodes and Keycode.ONE in keycodes:
        if inside_IDE == True:
            inside_IDE = False
            display_text(label, "OUTSIDE IDE")
        else:
            inside_IDE = True
            display_text(label, "INSIDE IDE")
            print("INSIDE IDE")

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
                listening_notification = False
                LED.value = False
                option_selected = True
            elif pressed_characters[0] == '\x08':
                current_prompt = current_prompt[:-1]
            elif (Keycode.CONTROL or Keycode.ALT or Keycode.GUI) not in keycodes:
                shifted_character = SHIFTED_CHARACTERS.get(
                    pressed_characters[0])
                if Keycode.SHIFT in keycodes and shifted_character is not None:
                    current_prompt += shifted_character
                else:
                    current_prompt += pressed_characters[0]
    

    return listening_for_prompt, listening_for_clipboard, listening_notification, option_selected, inside_IDE, call_api, current_prompt, keycodes, characters


if __name__ == '__main__':
    ret = connect_to_wifi(SSID, PASSWORD)
    if not ret:
        print("Connecting to aux wifi")
        ret = connect_to_wifi(SSID_AUX, PASSWORD_AUX)
    if not ret:
        print("Couldn't connect to wifi")
        exit()
    menu = Menu()
    pool = socketpool.SocketPool(wifi.radio)
    socket = initialize_tcp_server(pool)
    label = initialize_display()
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    current_uart_data = bytearray()
    current_serial_data = ''
    last_pressed_keycodes = []
    last_pressed_characters = []
    responses = []
    current_prompt = ''
    listening_for_prompt = False
    listening_notification = False
    viewing_response = False
    call_api = False
    LED.value = False
    last_position = 0
    button_state = None
    option_selected = True
    typing = True
    result = None
    listening_for_clipboard = False
    inside_IDE = False
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
                    keycodes, characters = parse_packet(
                        packet, modifier_pos=1, first_key_pos=3, last_key_pos=7)
                elif len(packet) == 9:
                    keycodes, characters = parse_packet(
                        packet, modifier_pos=0, first_key_pos=2, last_key_pos=6)
                else:
                    continue

                listening_for_prompt, listening_for_clipboard, listening_notification, option_selected, inside_IDE, call_api, current_prompt, keycodes, characters = process_keycodes(
                    keycodes,
                    characters,
                    current_prompt,
                    listening_for_prompt,
                    listening_for_clipboard,
                    listening_notification,
                    option_selected,
                    inside_IDE,
                    LED,
                    call_api,
                    label
                )
                last_pressed_keycodes = keycodes
                last_pressed_characters = characters
                typing = True
                if all(i == 0 for i in keycodes):
                    typing = False

                if listening_for_clipboard and not typing:
                    clipboard = accept_packet(socket)
                    current_prompt += str(clipboard, 'utf-8')
                    display_text(label, current_prompt)
                    listening_for_clipboard = False
                    del clipboard
                    gc.collect()

                if call_api == True and not typing:
                    call_api = False
                    current_prompt = menu.prompts[menu.current_option] + \
                        current_prompt
                    print(current_prompt)
                    viewing_response = True
                    listening_for_serial = False
                    listening_notification = False
                    option_selected = True
                    display_text(label, current_prompt)
                    result = call_chatgpt(current_prompt, requests, label, inside_IDE)
                    current_prompt += result.full_prompt

            current_uart_data = bytearray()

        if listening_for_prompt:
            if listening_notification == False:
                display_text(label, "Listening for prompt...")
                listening_notification = True
            # exception, current_serial_data = read_from_serial_monitor()
            # if len(current_serial_data) > 0 and exception == None:
            #     print("Serial data: " + current_serial_data)
            #     current_prompt += current_serial_data
            #     display_text(label, current_prompt)
            #     print(current_prompt)

        position = encoder.position
        if position != last_position:
            if viewing_response and result is not None:
                if position > last_position:
                    result.display_next_prompt(label)
                else:
                    result.display_previous_prompt(label)
            else:
                option_selected = True
                if position > last_position:
                    menu.next_option()
                else:
                    menu.previous_option()
        last_position = position
        if button.value and button_state is None:
            button_state = "pressed"
        if not button.value and button_state == "pressed":
            viewing_response = False
            button_state = None

        if not listening_for_prompt and not viewing_response and option_selected:
            option_selected = False
            display_list(label, menu.options, menu.current_option)
