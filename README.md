# sydpower-mqtt.py

This repository provides sydpower-mqtt.py, a Python3 script to help in the reverse engineering efforts of the SYDPOWER/FOSSIBOT/AFERIY mqtt protocol.  

Disclaimer: This tool is not affiliated to SYDPOWER, an OEM company that provides portable power stations for other companies such as FOSSIBOT and AFERIY.

In its current state, the script is only useful if the device MQTT traffic is redirected to a local MQTT server (see below)

## About SYDPOWER

The product page on SYDPOWER web page https://www.sydpower.com list mulptiple portable power stations:
   - the N052 is similar to the Fossibot F2400 and the AFERIY P210
   - the N066 is similar to the Fossibot F3600-Pro and the AFERIY P310 

The physical appearance can be different but the features are pretty much identical.

Fossibot and AFERIY batteries use the same BrightEMS application to control them via WiFi or Bluetooth.

## Related projects and sources

  - https://github.com/iamslan/fossibot is a non-official Fossibot integration for Home Assistant. Most of the information used here come from that project.
  - MQTT   (TODO)
  - MODBUS (TODO)

## Install a local MQTT server

During the development of the Home Assistant Integration, it was discovered that the BrightEMS app is communicating with the Sydpower cloud using a MODBUS-like protocol via MQTT at `mqtt.sydpower.com` port `1883`.

The credentials needed to access that MQTT server are obtained using requests to the sydpower cloud but those are not (yet) implemented in 'sydpower-mqtt.py'. Instead, it is possible to redirect the MQTT traffic to a local MQTT server by changing the local DNS settings for 'mqtt.sydpower.com'.

On your home network, that could be as simple as adding an entry for 'mqtt.sydpower.com' in the DNS settings of your home router. 

Otherwise, you may have to create a dedicated WiFi hotspot with a custom DNS. This is a more complex operation that can be done in a lot of differents way of various operating system. Be aware that the WiFi hotspot still need access to Internet because the battery still has to obtain MQTT credentials from the Sydpower cloud.   

Assuming that you have redirected 'mqtt.sydpower.com' to a local IP address, you need to install a MQTT broker on that machine. Common choices are [Mosquitto](https://www.mosquitto.org/) and  [EMQX](https://www.emqx.com/en/products/emqx). See https://mqtt.org/software/ for more choices.

That server should accept non-encrypted connections on port 1883 (this is the standard) and should allow anonymous connection (because the device will be using unpredictable username and password obtained from the cloud).

If you are using the Mosquitto broker then a basic listener configuration could be 
```
  per_listener_settings true
  
  # Listener for the Fossibot device.
  listener 1883
  protocol mqtt
  allow_anonymous true
```

Once everything is up and running, the device should start publishing messages to the local MQTT broker.

The message topics all start by the MAC address of the device so something like '7D24F75BCC2B'. It is probably written on a stiker on the device or it can be obtained in the device selection page of the BrightEMS application. 

If the Mosquitto Client utilities are installed, you can use `mosquitto_sub` to display the messages:

```
[shell] mosquitto_sub -t '7D24F75BCC2B/#' -F "%t %l %x"
7D24F75BCC2B/device/response/client/04 168 11040000005000000000000100000000000000000000000000000000000000000000000000000000000008fe01f4000800a000000000000000000000000000000000000000000000000000000000000000000000000800000804000000000000000000003000400000000000000000b400000188000002380000000008860000000000ffffff0000000000000000000000000000000000000000000000000000000000000000c314
```

## Requirements 

- Python 3 packages
  - Paho-MQTT (https://pypi.org/project/paho-mqtt). Tested with version 2.1.0

## Running the script

The command line syntax is

```
python3 sydpower-mqtt.py [GLOBAL-OPTIONS...] [COMMAND] [COMMAND-OPTIONS...] 
```

- Use `-h` or `--help` before the COMMAND to get help about the global options.
- Use `-h` or `--help` after the COMMAND to get help about that specific command.

As of May 12th 2025, the following commands are implemented:
  - `monitor` : Display all MODBUS-MQTT messages with partial decoding (when possible).
  - `trace` : Trace changes to input and holding registers. 
  - `help` : Display additional help
    - register names
    - interpretation of status bits
    - ...

## MQTT-MODBUS protocol

All known informatons about the MQTT-MODBUS protocol used by Sydpower can be found in [MQTT-MODBUS.md](MQTT-MODBUS.md)

## How to use the script ? 

The monitor command is pretty straightforward but not that useful.

The trace command will display all changes to a selected set of registers.

Quick summary:
   - 80 input registers and 80 holding registers.
   - Each register contains a 16 bit integer.
   - The input registers are read-only.
   - The holding registers shall be writable but in practice, most of them are read-only.
   - Any Input or Holding registers whose behavior is known is given a proper name starting with either 'i' or 'h'. 
   - For other registers, the name is simply 'i' or 'h' followed by the register number.
   - Use the `help` command to display all register names and a few other useful information.
   - See the file [MQTT-MODBUS.md](MQTT-MODBUS.md) for a detailled description of each register.
   - The trace command also recognize a few register groups. For example, `iNAMED` means all input register with an explicit name while `iOTHER` means all other input registers (i.e. those of the form `i<NUMBER>`).
   

Important: It is strongly advised to run the trace command with the option `-q` to explicitly query register updates every few seconds. Without `-q`, registers may not be updated for a very long time.

Examples:

- Trace all named input registers 
```
python3 sydpower-mqtt.py trace -q iNAMED 
```
- Trace iAcOutputPower and iTotalOutputPower  
```
python3 sydpower-mqtt.py trace -q iAcOutputPower iTotalOutputPower 
```
- Trace all unamed registers (those of the form `i<NUMBER>` and `h<NUMBER>`)
with timestamps
```
python3 sydpower-mqtt.py trace -t -q OTHER 
```
