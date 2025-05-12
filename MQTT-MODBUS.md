

# Analysis of the MQTT protocol of the Fossibot batteries (F2400, F3600-pro)

This document is based on https://github.com/iamslan/fossibot (HomeAssistant integration for Fossibot batteries)
and some personal experiments on my F2400.

Note: This document is not applicable to the first generation of F2400 that lacks WiFi capabilities.

Note: The same protocol is probably used by AFERIY devices and other brands related to Sydpower. 

> [!CAUTION]
**Writing bad values in unknown registers can BRICK your device. Remember that the information provided in that document are not official. Use at your own risk!!!!**

## History

- 2025-04-07 first version
- 2025-04-08 add Key Sound (holding 56) 
- 2025-04-08 add note about delay between requests
- 2025-04-12 update bit 2 of input register 41 (not EPS) 
- 2025-04-12 add iregs 30,31,34,35,36,37 as output power of USB ports   
- 2025-04-12 add ireg 9 as output power of DC car port (or of all DC ports?)   
- 2025-04-12 add ireg 58 and 59 : time to full or empty
- 2025-04-12 add ireg 3 as charging power
- 2025-04-12 add ireg 2 as AC charging rate
- 2025-04-12 add ireg 57 as AC Charging Booking


## How to connect the Fossibot to a local MQTT server ?

With WiFi, the Fossibot is (probably) connecting to a cloud server to obtain the MQTT credentials
before opening a non-encrypted MQTT connection to  mqtt.sydpower.com port 1883.

The MQTT login and passwords are not required but, as of May 7th 2025, an internet connection is still required by the Fossibot.

A reverse-engineering of that initial cloud connection is still needed before being able to operate entirely locally.

It is also very well possible that the MQTT host and port are defined by the cloud server. If so, they could be change at any time.   

So the trick is simply to change the IP address of mqtt.sydpower.com to that a local MQTT server. 

- **Method 1** Use the IPv4 DNS settings of your local router or Internet box.

  This is the method I used on my home network (SFR NB6 internet box).
  
  So I simply added an entry for `mqtt.sydpower.com` in the IPv4 DNS section.

  Note: You may have to toggle the WiFi off and on to force the Fossibot from using the new IP of `mqtt.sydpower.com` 

- **Method 2** Create a WiFi hotspot with custom DNS settings
  
  There are several ways to do that and the method and tools depends of your OS and personal preferences. 


The local MQTT server shall listen to port 1883 and, since the Fossibot will be
using credentials obtained from the cloud, it shall allow anonymous access.

It shall be noted that the Fossibot Home Assistant integration is currently
connecting to 'mqtt.sydpower.com', port 8083, websocket protocol with
credentials also obtained from the cloud. The local MQTT server shall
also enable that port with anonymous access if you intend to use the 
Fossibot Home Assistant integration.

TODO: The Fossibot Home Assistant integration shall have configurable
      MQTT host, port, protocol and credentials when connecting locally.
      No need to query the cloud. 

Example of 'listener' configuration for the Mosquitto MQTT server:
```
  per_listener_settings true
  
  # Listener for the Fossibot device.
  listener 1883
  protocol mqtt
  allow_anonymous true

  # Listener for the Fossibot HomeAssistant integration.
  listener 8083
  protocol websocket
  allow_anonymous true
```

## MODBUS over MQTT

The messages are using a protocol similar to MODBUS but adapted to MQTT.

Here are some good starting points for MODBUS:
  - [SPEC] https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf
  - [WIKI] https://en.wikipedia.org/wiki/Modbus
  
Only a small subsect of the MODBUS features appear to be implemented:
   - 80 holding registers (read-write 16 bits)
   - 80 input registers (read-only 16 bits)   
   - function 0x03: Read Holding Registers
   - function 0x04: Read Input Registers
   - function 0x06: Write Holding Register

Also, not all holding registers are actually writable via MQTT.

A major difference with the standard MODBUS protocol is that the response to
Read Holding Registers (function 3) and Read Input Registers (function 4)
contains the range of registers. 

## MQTT topics

Each MQTT topic starts by the MAC address of the Fossibot device in uppercase hex format
so something like `7CAD643BFDFA`.

In the following, we will be using `ABCDEF123456` as the device MAC address.  

  - **ABCDEF123456/client/request/data**

    This is the topic used by the client to send requests to the device 

> [!CAUTION]
**Insert a small delay between consecutive requests otherwise some of them may be ignored. Ideally, the next request should be delayed until the previous response is received**

  - **ABCDEF123456/device/response/state**

    That topic is used by the device to send messages with a payload
    composed of a single byte:
      - 0x30 when the device is turning itself off (e.g. using the power button) 
      - 0x31 when the device is re-connected

  - **ABCDEF123456/device/response/client/data**
  
    This is the default topic used by the device to send data to the client
    except for the responses to function 0x04 (Read Input Registers).    
    
  - **ABCDEF123456/device/response/client/04**
  
    This topic is used by the device to send input register values to the client
    (i.e 0x04 responses). It should be noted that the device is
    automatically sending a full 0x04 response (all 80 input registers) once
    every minute.

    The reason for that dedicated topic is that the device is producing Retained Messages.
    https://www.emqx.com/en/blog/mqtt5-features-retain-message
    Simply speaking, the last message is memorized by the MQTT server and re-emited
    each time a MQTT client is subscribing to the topic.

    This is used to inform the clients of the last known state of the device when it
    is off-line. 

    IMPORTANT: If the client is explicitly calling function 4, Read Input Registers, it
    is probably a good idea to always use the full register range. Otherwhise the retained
    message could be incomplete which could confuse clients that expect to receive a full state
    at startup.

    REMARK: There is unfortunately no easy way to know the age of a MQTT retained message.
    They may also have a timeout so the client shall not expect to always receive one
    after subscription.

    TODO: I was under the impression that the real mqtt.sydpower.com server was sending
    those retained messages once every minute even when the device is offline. I may have
    been mistaken since that could be an side-effect of frequent disconnections and reconnections
    by the other clients.     
          
## Generic MODBUS message format    

Messages sent to `ABCDEF123456/client/request/data`, `ABCDEF123456/device/response/client/data` and `ABCDEF123456/device/response/client/04`
are formatted in a similar manner.

Here, all MODBUS messages are using 0x11 as their 'Slave Address'.

My guess is that different components within the battery are using MODBUS to communicate and
0x11 is the slave address used by the internal client that acts as a bridge with MQTT. 

All client queries are sent using topic `ABCDEF123456/client/request/data`

- The payload is in binary big-endian (so most significant byte first)
- The first byte is the slave address 0x11. 
  My guess is that 0x11 is slave address for the MQTT client. Other MODBUS clients within the battery
  may use a different 
- The second byte is a function code. 
- The arguments to the function (usually 16bit per argument)
- a 16bit CRC

Responses from the devices are sent to `ABCDEF123456/device/response/client/data` or `ABCDEF123456/device/response/client/04`

The response is usually a verbatim copy of the query with a payload inserted before the CRC.  

The device can also reply with an error by setting the most significant bit of the function code.
For example, a query of the unsupported function `0x01` can result in an response with function code `0x81`.


## CRC format

Here is a python function to compute the 16 bit CRC for a message.

```python
def MODBUS_CRC16(buf, length):
    crc = 0xFFFF
    for i in range(length):
        crc ^= buf[i]
        for bit in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc  
```

## Supported MODBUS functions

In the following examples, both client and device messages are made more readable by 
  - Converting them to hexadecimal
  - Inserting spaces between bytes or words.
  - Enclosing the arguments between () 
  - Enclosing the payload between {} where applicable
  - Enclosing the CRC between [] 

### function 0x03 - Read Holding Registers

The two 16-bit parameters are
  - the index of the first holding register
  - the numbers of holding registers
  
The payload in the response contains one 16 bits value per register 

Example: read the 5 registers 0x20 .. 0x24
```
ABCDEF123456/client/request/data         : 11 03 (0020 0005) [9386]
ABCDEF123456/device/response/client/data : 11 03 (0020 0005) {0203 0000 0000 0000 0000} [6647]
```

### function 0x04 - Read Input Registers

The two 16-bit parameters are
  - the index of the first holding register
  - the numbers of holding registers
  
The payload in the response contains one 16 bits value per register 

Reminder: The response is sent to a dedicated topic with a RETAINED status

Example: read the 3 registers 0x3a, 0x3b and 0x3c
```
ABCDEF123456/client/request/data       : 11 04 (003a 0003) [9692] 
ABCDEF123456/device/response/client/04 : 11 04 (003a 0003) {0000 0690 0000} [0a54]
```

### function 0x06 - Write Holding Register

The two arguments are
  - the index of the holding register
  - the new value for the holding register

The response is usually a verbatim copy of the query. However, that does not mean that
the value was successfully changed since some holding registers cannot be modified.

Example: Write 1 in holding register 0x0039 (enable AC Silent Charging)
```
ABCDEF123456/client/request/data         : 11 06 (0039 0001) [979a]
ABCDEF123456/device/response/client/data : 11 06 (0039 0001) [979a]
```

## Desciption of the Input registers
TODO
### Input register 3 - Charging Power
- Provide the power used to charge the battery
  - from AC, DC or both? More tests are required!
- value is given in Watts
### Input register 4 - DC Input Power
- Provide the DC input power (from the XT90 port)
- value is given in Watts
### Input register 6 - Total Input Power 
- Provide the total input power (AC+DC)
- value is given in Watts 
### Input register 9 - DC Ouput Power 1 
- Provide the output power of the DC car-charging port.
  - Or of all DC outputs? More tests are needed! 
- value is given in 1/10 Watts 
### Input register 15 - Led Power
- Provide the Power consumed by the front led (probably)
- This is 0 when off and 10 when on (so 1.0 W)  
- Value is given in 1/10 Watts
### Input register 18 - AC Output Voltage 
- Provide the AC output voltage.
- value is given in 1/10 Volts.
### Input register 19 - AC Output Frequency
- Provide the AC output frequency
- Only when AC output is enabled.
- Value is given in 1/10 Hz
### Input register 20 - AC Output Power
- Provide the AC output power
- Value is given in Watts
### Input register 21 - AC Input Voltage 
- Provide the AC input voltage
- Only when AC input is connected to grid.
- Value is given in 1/10 Volts
### Input register 22 - AC Input Frequency
- Provide the AC input frequency
- Only when AC input is connected to grid.
- Value is given in 1/100 Hz
### Input register 25 - Led State
- Provide the state of the front led
  - 0 : Off
  - 1 : On mode
  - 2 : SOS mode
  - 3 : Flash mode
- see also holding register 27
### Input register 30 - USB Output Power 1
- Provide the output power of the 1st USB port
- Fossibot F2400: one of the USB-A ports
- Value is given in 1/10 Watt
### Input register 31 - USB Output Power 2
- Provide the output power of the 2nd USB port
- Fossibot F2400: one of the USB-A ports
- Value is given in 1/10 Watt
### Input register 34 - USB Output Power 3
- Provide the output power of the 2nd USB port
- Fossibot F2400: the USB-C 100W port
- Value is given in 1/10 Watt
### Input register 35 - USB Output Power 4
- Provide the output power of the 2nd USB port
- Fossibot F2400: one of the USB-C 20W ports 
- Value is given in 1/10 Watt
### Input register 36 - USB Output Power 5
- Provide the output power of the 2nd USB port
- Fossibot F2400: one of the USB-C 20W ports
- Value is given in 1/10 Watt
### Input register 37 - USB Output Power 6
- Provide the output power of the 2nd USB port
- Fossibot F2400: one of the USB-C 20W ports 
- Value is given in 1/10 Watt
### Input register 39 - Total output   
- Provide the total output voltage so AC+DC+USB
- Value is given in Watts.
### Input register 41 - Status bits
- bit 15, mask 0x8000 = Always zero?
- bit 14, mask 0x4000 = Always zero?
- bit 13, mask 0x2000 = Always zero?
- bit 12, mask 0x1000 = LED is enabled
  - see also holding register 27
- bit 11, mask 0x0800 = AC output is enabled 
  - see also holding register 26 
- bit 10, mask 0x0400 = DC output is enabled
  - see also holding register 25  
- bit  9, mask 0x0200 = USB ouput is enabled
  - see also holding register 24   
- bit  8, mask 0x0100 = Always zero?
- bit  7, mask 0x0080 
  - Set when LED, DC or USB is used so probably indicates the state of an internal DC converter. 
- bit  6, mask 0x0040 = Always zero?
- bit  5, mask 0x0020 = Always zero?
- bit  4, mask 0x0010 = Charging from AC 
  - Checked: no set during AC booking if AC input is connected.
  - TODO: Check that it is not set either when battery is full.   
- bit  3, mask 0x0008 = AC input is connected 
   - Same as bit 1? 
- bit  2, mask 0x0004 = AC output is enabled 
   - same as bit 11?
- bit  1, mask 0x0002 = AC input is connected 
   - Same as bit 3? 
- bit  0, mask 0x0001 = always zero?

- Potential candidates for the unknown bits (TO BE TESTED):
  - DC Charging. There could also be distinct bits to differentiate DC charging from PV and from a battery
  - Slow charging (when SOC>85%)
  - AC output is 50Hz or 60Hz
  - AC output is 220V or 230V
  - The state of the Overload Protection Button
  - The Fan
### Input register 42
  - For the F2400:
     - contains the sum of 0x03d8 (if USB output) and 0xe000 (if DC output)
### Input register 48
  - For the F2400:
     - contains 0x8000 while AC charging otherwise 0x4000.
     - can also briefly contain 0x0000  
     
### Input register 53 - State of Charge S1
  
  - Provide the state of charge of the 1st extension battery
  - 0 when the extension battery is missing
  - otherwise a value between 10 and 1010.
     - for example, value 504 means 49.4%      
 
### Input register 55 - State of Charge S2

  - Similar to input register 53 but for the 2nd extension battery.
  
### Input register 56 - State of Charge (SOC)
  - Provide the state of charge of the main battery. 
  - Value ranges is 0 to 1000. For instance `435` means `43.5%` 

### Input register 57 - AC Charging Booking
 - If non-zero, this is a timeout in minute during which AC charging will be disabled.
 - See also the holding register 66 
 - The official app allows up to 24 hours so a maximum of `24*60-1 = 1439` minutes but bigger values may very well be possible (NOT TESTED)

### Input register 58 - Time To Full
  - Provide the estimated time in minutes until the battery is fully
    charged or 0 when the battery is currently discharging

### Input register 59 - Time To Empty
  - Provide the estimated time in minutes until the battery is fully
    discharged or 0 when the battery is currently charging.
    
## Description of the Holding registers

### Holding register 13 (0x0D) - AC Charging Rate
- This is state of the charging wheel
  - The actual charging rate can be different.   
- read-only 
- value is between 1 and 5
- For the F2400, that means 300W, 500W, 700W, 900W and 1100W
- For the F3600 pro, that means 400W, 800W, 1200W, 1600W  and 2200W
 
 
### Holding register 20 (0x14) - Maximum (DC?) Charging Current 
 - TODO

### Holding register 24 (0x18) - USB Output switch

- Control the USB output.
- read-write 
  - 0x00 : Off
  - 0x01 : On

### Holding register 25 (0x19) - DC Output switch

- Control the DC output.
- read-write 
  - 0x00 : Off
  - 0x01 : On

### Holding register 26 (0x1a) - AC Output switch

- Control the AC output.
- read-write 
  - 0x00 : Off
  - 0x01 : On

### Holding register 27 (0x1b) - Led Control

- Control the front led.
- read-write 
  - 0 : Off
  - 1 : On mode
  - 2 : SOS mode
  - 3 : Flash mode

### Holding Register 56 (0x38) - Key Sound 
 
- read-write 
  - 0 : Off
  - 1 : On 
   
### Holding Register 57 (0x39) - AC Silent Charging  

- Control the AC Silent Charging feature 
- read-write 
  - 0 : Off
  - 1 : On 

### Holding Register 59 (0x3B) - USB Standing Time
- TODO

### Holding Register 60 (0x3C) - AC Standing Time
- TODO

### Holding Register 61 (0x3D) - DC Standing Time
- TODO

### Holding Register 62 (0x3E) - Screen Rest Time
- TODO

### Holding Register 63 (0x3F) - AC Charging Booking
 - If non-zero, this is a timeout in minute during which AC charging will be disabled.
 - See also the holding input register 57 
 - The official app allows up to 24 hours so a maximum of `24*60-1 = 1439` minutes but bigger values may very well be possible (NOT TESTED)

### Holding Register 66 (0x42) - Discharge Lower Limit
 - read-write (TO BE TESTED)
 - Value unit is 1/10 percent so 0 to 1000
 - the range allowed in the official app is 0 (0%) to 500 (50%)
 
### Holding Register 67 (0x43) - AC Charging Upper Limit
 - read-write (TO BE TESTED)
 - Value unit is 1/10 percent so 0 to 1000
 - the range allowed in the official app is 600 (60%) to 1000 (100%)
 
### Holding Register 68 (0x44) - Whole Machine Unused Time
- read-write
- The time is given in minutes
- The official app allows for 5, 10, 30 and 480 
> [!CAUTION] 
**Settting Whole Machine Unused Time to zero is known to brick the device. Use with care**





