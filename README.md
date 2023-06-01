# Plug & Play ChatGPT

The code for a device that let's you use ChatGPT on any computer, inside any application.

Schematics at https://github.com/nan-dre/plug-n-play-chatGPT-docs

## Building the tinyUSB library
```bash
cd example
mkdir build
cd build
cmake ..
cd capture_hid_report
make
```
## Installing
Copy UF2 file in capture_hid_report/ to Raspeberry Pi Pico, when in BOOT mode (hold BOOT button and connect to pc).
Copy the files in circuit-python-porcessor to a Raspberry Pi Pico W, after you flashed CircuitPython on it.

## Credits

TinyUSB implementation forked from https://github.com/sekigon-gonnoc/Pico-PIO-USB