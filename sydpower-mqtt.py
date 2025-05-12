#!/usr/bin/python3

import os
import sys
import paho.mqtt.client as mqtt
import argparse
import time
import queue
import signal
import random
import datetime
from typing import Union, Sequence, Any

#
# modbus_values is a list[int] but where some values can be replaced by their symbolic equivalent, so a str.
#
# Ideally, I should use list[int|str] but that does not work as expected.
#
type modbus_values = list[Any]

# 
# A representation of a modbus message payload either as a list of integer (usually 16 bit each) or as a raw byte sequence. 
#
type modbus_payload = list[int] | bytes

# Notes:
#   - The abbreviation ireg or IREG stands for Input Register so 16 bit read-only registers
#   - The abbreviation hreg or HREG stands for Holding Register so 16 bit writable registers
#

# References
#
#  Paho API  
#    https://eclipse.dev/paho/files/paho.mqtt.python/html/index.html
#    https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html


HREG_COUNT=80
IREG_COUNT=80

#
# Put here all input registers with a known name.
# Please keep the 'i' prefix to avoid confusion with holding registers.
# Other registers will be named 'iNN' where NN is the two-digits register
# index.
#
NAMED_INPUT_REGISTERS = {
    4:'iDcInputPower' ,
    6:'iTotalInputPower' ,
    18:'iAcOutputVoltage',
    19:'iAcOutputFreq',
    21:'iAcInputVoltage',
    22:'iAcInputFreq',
    39:'iTotalOutputPower',
    41:'iStatusBits',
    53:'iSOC1',
    55:'iSOC2',
    56:'iSOC',    
}


#
# Put here all holding registers with a known name.
# Please keep the 'h' prefix to avoid confusion with input registers.
# Other registers will be named 'hNN' where NN is the two-digits register
# index.
#
NAMED_HOLDING_REGISTERS = {
    13:'hAcChargingRate' ,    
    20:'hMaxDcChargingCurrent' ,
    24:'hUsbOutputSwitch' ,  
    25:'hDcOutputSwitch' , 
    26:'hAcOutputSwitch' ,
    27:'hLedControl',
    56:'hKeySound',   
    57:'hAcSilentCharging' ,    
    59:'hUsbStandbyTime',
    60:'hAcStandbyTime',
    61:'hDcStandbyTime',
    62:'hScreenRestTime',
    63:'hAcBookingCharging',
    66:'hDischargeLowerLimit',
    67:'hAcChargingUpperLimit',
    68:'hWholeMachineUnusedTime',
}


# Provide the full mapping between holding register names and indices 
HREG_INDEX_TO_NAME = { x: (NAMED_HOLDING_REGISTERS.get(x,'h{:02d}'.format(x))) for x in range(HREG_COUNT) }
HREG_NAME_TO_INDEX = { v: k for k, v in HREG_INDEX_TO_NAME.items() }

# Provide the full mapping between input register names and indices 
IREG_INDEX_TO_NAME : dict[int,str] = { x: (NAMED_INPUT_REGISTERS.get(x,'i{:02d}'.format(x))) for x in range(IREG_COUNT) }
IREG_NAME_TO_INDEX = { v: k for k, v in IREG_INDEX_TO_NAME.items() }

# Prefined sets of holding register names
HREG_SETS={} 
HREG_SETS['hALL']   = set( HREG_NAME_TO_INDEX.keys() )
HREG_SETS['hNAMED'] = set( NAMED_HOLDING_REGISTERS.values() )
HREG_SETS['hOTHER'] = HREG_SETS['hALL'].difference(HREG_SETS['hNAMED']) 

# Prefined sets of mappig register names
IREG_SETS={} 
IREG_SETS['iALL']   = set( IREG_NAME_TO_INDEX.keys() )
IREG_SETS['iNAMED'] = set( NAMED_INPUT_REGISTERS.values() )
IREG_SETS['iOTHER'] = IREG_SETS['iALL'].difference(IREG_SETS['iNAMED']) 

def format_dec(v:int):
    return "{:<5d}".format(v)

def format_dec_hex(v:int):
    return "{:<5d} = 0x{:04x}".format(v,v)

def format_dec_hex_bin(v:int):
    return "{:<5d} = 0x{:04x} = {:08b}:{:08b}".format(v,v,(v>>8)&0xFF,v&0xFF)

def format_iStatusBits(v:int):

    # L = bit 12 = Front LED panel is enabled 
    # A = bit 11 = AC ouput is enabled 
    # D = bit 10 = DC output is enabled
    # U = bit 9  = USB output is enabled
    # X = bit 7  = Set when LED, DC, or USB is enabled
    # C = bit 4  = Charging from AC
    # a = bit 3  = AC input is connected  
    # A = bit 2  = Always identical to bit 11?
    # a = bit 1  = Always identical to bit 3?
    #
    # Other bits marked as '?' are currently unknown.
    #
    
    on  = '???LADU?X??CaAa?'
    off = '----------------'

    bits=''
    for i in range(16):
        if (v>>i)&1 :
            bits = on[15-i] + bits
        else:
            bits = off[15-i] + bits
    return "{:<5d} = 0x{:04x} = {} {} {} {}".format(v,v,bits[0:4],bits[4:8],bits[8:12],bits[12:16])

def help_iStatusBits():
    print("The content of iStatusBits is currently interpreted as follow:")
    print("  L = bit 12 = Front LED panel is enabled")
    print("  A = bit 11 = AC ouput is enabled")
    print("  D = bit 10 = DC output is enabled")
    print("  U = bit 9  = USB output is enabled")
    print("  X = bit 7  = Set when LED, DC, or USB is enabled")
    print("  C = bit 4  = Charging from AC")
    print("  a = bit 3  = AC input is connected")
    print("  A = bit 2  = Always identical to bit 11?")
    print("  a = bit 1  = Always identical to bit 3?")
    print("Other bits are unknown and will be with marked with '?' when set")
    
    
# Entries in that dictionary specify an optional function to format the
# register values. The index is the register name while the value is 
# a callable that expects a single integer as argument.
#
# The result shall be a string
#
FORMATTER = {
    'iStatusBits' : format_iStatusBits
}

for i in HREG_SETS['hOTHER'] | IREG_SETS['iOTHER']:
    if i not in FORMATTER:
        FORMATTER[i] = format_dec_hex




#print(HREG_INDEX_TO_NAME)
#print(HREG_NAME_TO_INDEX)

def timestamp():
    return "["+datetime.datetime.now().isoformat()+"]"

def hreg_index_to_name(index: int):
     return HREG_INDEX_TO_NAME.get(index)

def hreg_name_to_index(name: str):
     return HREG_NAME_TO_INDEX.get(name)

# Sort a list of holding register names according to their indices
def hreg_sort_by_index(holdings: list[str] | set[str] ):
    return sorted(holdings, key=hreg_name_to_index)

def ireg_index_to_name(index: int):
     return IREG_INDEX_TO_NAME.get(index)

def ireg_name_to_index(name: str):
    return IREG_NAME_TO_INDEX.get(name)

# Sort a list of input register names according to their indices
def ireg_sort_by_index(inputs: list[str] | set[str]):
    return sorted(inputs, key=ireg_name_to_index)

def help_register_names():
    print('Input Registers:')
    for i in range(IREG_COUNT): 
        if i in NAMED_INPUT_REGISTERS:
            print('  {:2d} {}'.format(i,ireg_index_to_name(i)))
    print('or \'i<NUMBER>\' for other input registers' )
    print()
    
    print('Holding Registers:')
    for i in range(HREG_COUNT): 
        if i in NAMED_HOLDING_REGISTERS:
            print('  {:2d} {}'.format(i, hreg_index_to_name(i))) 
    print('or \'h<NUMBER>\' for other holding registers' )
    print()
    print("Aliases:")
    print(" - iALL,   hALL,   ALL   : all input, holding or both registers")
    print(" - iNAMED, hNAMED, NAMED : all named input, holding or both registers")
    print(" - iOTHER, hOTHER, OTHER : all unnamed input, holding or both registers")
    print()

#
# Parse a list of register names and return two lists of input and holding register names
#
# Both lists are sorted by increasing register indices
#
def parse_register_names(names:list):
    
    inputs   = set()
    holdings = set()
    
    for name in names:
        
        if name in HREG_SETS['hALL']:
            holdings.add(name)
        elif name in IREG_SETS['iALL']:
            inputs.add(name)            
        elif name in HREG_SETS:            
            holdings.update(HREG_SETS[name])
        elif name in IREG_SETS:            
            inputs.update(IREG_SETS[name])
        elif name=='ALL':
            holdings.update(HREG_SETS['hALL'])
            inputs.update(IREG_SETS['iALL'])
        elif name=='NAMED':
            holdings.update(HREG_SETS['hNAMED'])
            inputs.update(IREG_SETS['iNAMED'])
        elif name=='OTHER':
            holdings.update(HREG_SETS['hOTHER'])
            inputs.update(IREG_SETS['iOTHER'])
        else:            
            print("Error: Unknown register '"+name+"'")
            sys.exit(1)
    
    inputs   = ireg_sort_by_index(inputs)
    holdings = hreg_sort_by_index(holdings)

    return inputs, holdings


#
# That class provide various features related to MODBUS 
#
class SydpowerModbus:
            
    CHANNEL=0x11

    FUNC_READ_HOLDING_REGISTERS=3
    FUNC_READ_INPUT_REGISTERS=4
    FUNC_WRITE_HOLDING_REGISTER=6

    # Compute a CRC for a modbus message    
    def compute_crc(self, buf, size:int):
        crc = 0xFFFF
        for i in range(size):
            crc ^= buf[i]
            for bit in range(8):
                if crc & 0x0001:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1

        return [ (crc & 0xFF00) >> 8 , crc & 0xFF ]

    def append_crc(self, buf: bytearray):
        hi,lo = self.compute_crc(buf,len(buf))
        buf.append(hi)
        buf.append(lo)

    def check_crc(self, buf):
        if len(buf) < 2:
            return False
        hi,lo = self.compute_crc(buf,len(buf)-2)
        return (hi==buf[-2] and lo==buf[-1])

    # Extract a single 16 word from a bytes or bytearray buffer
    def get_word(self, buf: bytes|bytearray , index:int) -> int:
        try:
            return ((buf[index]&0xFF)<<8) + (buf[index+1]&0xFF)
        except:
            raise Exception('[modbus] malformed message')

    # Extract n 16bit words from a bytes of bytearray buffer 
    def get_words(self, buf: bytes|bytearray, index:int, n:int) -> modbus_values :
        return list( self.get_word(buf,index+2*x) for x in range(n) )

    # Append a 16 bit word at the end of bytearray 
    def append_word(self, buf:bytearray ,value:int) -> None :
        buf.append((value>>8)&0xFF)
        buf.append(value&0xFF)

    def check_size(self, buf: bytes|bytearray , arg_size:int, payload_size:int) -> None:
        if len(buf) != 4+arg_size+payload_size :
            raise Exception('[modbus] malformed message')

    def encode_ReadHoldingRegisters(self, start:int, count:int) -> bytearray :
        msg = bytearray()
        msg.append(self.CHANNEL)
        msg.append(self.FUNC_READ_HOLDING_REGISTERS)
        self.append_word(msg,start)
        self.append_word(msg,count)
        self.append_crc(msg)
        return msg

    def encode_ReadInputRegisters(self, start:int, count:int) -> bytearray :
        msg = bytearray()
        msg.append(self.CHANNEL)
        msg.append(self.FUNC_READ_INPUT_REGISTERS)
        self.append_word(msg,start)
        self.append_word(msg,count)
        self.append_crc(msg)
        return msg
    
    # Decode a modbus message.
    #
    # The argument kind shall be
    #  - 'request' for a message from the client
    #  - 'response' for a message from the device
    #
    # The argument symbolic indicates if register numbers
    # shall be replaced by their symbolic name when possible.
    #
    def decode(self, msg:bytes, kind:str, symbolic:bool) ->  tuple[str, modbus_values, modbus_payload , int]: 

        channel : int
        crc: int
        func: int | str
        payload: modbus_payload
        n: int
        args: modbus_values
        name: str | None
        
        if kind not in ['request','response']:
            raise Exception('[modbus] bad kind argument')

        if len(msg)<4:
            raise Exception('[modbus] tiny message')
        channel = msg[0]
        if channel != self.CHANNEL:
            raise Exception('[modbus] Unexpected channel')
        if not self.check_crc(msg):
            raise Exception('[modbus] Bad CRC')
        crc = self.get_word(msg,-2)       
        func = msg[1]

        if func == self.FUNC_READ_HOLDING_REGISTERS:
            args = self.get_words(msg,2,2) # index and count
            n=args[1] if kind=='response' else 0
            self.check_size(msg, 2*2, n*2) 
            payload = self.get_words(msg,6,n)
            func = "ReadHoldingRegisters"
            if symbolic and n==1:
                name = hreg_index_to_name(args[0])
                if name:
                    args[0] = name                

        elif func == self.FUNC_READ_INPUT_REGISTERS:
            args = self.get_words(msg,2,2) # index and count
            n=args[1] if kind=='response' else 0
            self.check_size(msg, 2*2, n*2) 
            payload = self.get_words(msg,6,n)
            func = "ReadInputRegisters"

            if symbolic and n==1:
                name = ireg_index_to_name(args[0])
                if name:
                    args[0] = name

        elif func==self.FUNC_WRITE_HOLDING_REGISTER :
            args = self.get_words(msg,2,2) # index and value
            self.check_size(msg, 2*2, 0)
            payload = []
            func = "WriteHoldingRegister"

            if symbolic:
                name = hreg_index_to_name(args[0])
                if name:
                    args[0] = name

        else:
            # Unknown function so assume no arguments and a byte payload
            args=[]
            payload = msg[2:-2]  
            func = "Func"+str(func)

        return func, args, payload, crc


#
# A simple base class for MQTT clients: 
#
# Provide:
#   - a main loop
#   - for MQTT event (on_connect, on_disconnect, on_subscribe, on_message) 
#   - a callback called at regular interval (TIC)
#
#
class SimpleMqttApp :

    # args is typically a 'argparse.Namespace' object but any object with 
    # the following attributes will do (or use setattr(args, NAME, VALUE) to
    # manually set attributes).
    #
    #  - args.mqtt_hostname   (str)       The hostname or IP address of the mqtt server
    #  - args.mqtt_port       (int)       The MQTT port
    #  - args.mqtt_username   (str|None)  The MQTT username
    #  - args.mqtt_password   (str|None)  The MQTT password
    #
    def __init__(self, args) :

        # print(type(args))
        
        self.mqtt_hostname = args.mqtt_hostname
        self.mqtt_port     = args.mqtt_port 
        self.mqtt_username = args.mqtt_username
        self.mqtt_password = args.mqtt_password

        self.tic_interval = 0.1   # minimal interval in seconds between two tics 

        self._last_tic_time = time.time()   # When self.on_tic was last called

        self.event_queue = queue.Queue()
        
        self.result = None   # Setting this to any value will stop the run()  

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            
        if self.mqtt_username:
            self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)

        self.mqtt_client.on_connect    = self._on_connect_cb
        self.mqtt_client.on_disconnect = self._on_disconnect_cb
        self.mqtt_client.on_message    = self._on_message_cb
        self.mqtt_client.on_subscribe  = self._on_subscribe_cb

    def _on_connect_cb(self, client, userdata, flags, reason_code, properties):
        self.event_queue.put( ['connect', flags, reason_code, properties ] )

    def _on_disconnect_cb(self, client, userdata, flags, reason_code, properties):
        self.event_queue.put( ['disconnect', flags, reason_code, properties ] )
        
    def _on_message_cb(self, client, userdata, msg):
        self.event_queue.put( ['message', msg ] )

    def _on_subscribe_cb(self, client, userdata, mid, reason_code_list, properties):
        # TODO 
        # See /usr/lib/python3/dist-packages/paho/mqtt/reasoncodes.py
        # Note: is rc.value supposed to be a public attribute
        #       or are we supposed to use rc.is_failure to detect failure and
        #       then rc.getName() to display the reason?
        # Also the 'mid' would need to be matched with the result of
        # the client.subscribe() call.
        for rc in reason_code_list:
            if rc.is_failure:                
                print("==> Warning subscribe error mid=%d value=%d name='%s' "
                      % ( mid, rc.value, rc.getName() ) )
        pass

    #
    # For now, this is just an alias for self.client.subscribe(...)
    # 
    # TODO: Check for success in on_subscribe_cb
    #
    def subscribe(self, topic, qos=0):
        return self.mqtt_client.subscribe(topic,qos)  

    def publish(self, topic, payload, qos=0, retain=False, properties=None):
        return self.mqtt_client.publish(topic, payload, qos, retain, properties)  
    
    def on_message(self, msg):
        print("# "+msg.topic+" "+ msg.payload.hex())

    def on_connect(self, flags, reason_code, properties):
        pass
    
    def on_disconnect(self, flags, reason_code, properties):
        # TODO: Provide automatic reconnection.
        pass

    def on_tic(self):
        pass

    def run(self) :

        try:
            self.mqtt_client.connect(self.mqtt_hostname, self.mqtt_port, 60)
        except ConnectionRefusedError:
            # TODO: add support fro automatic reconnection
            print("Error: MQTT Connection refused on '{}' port {}".format(self.mqtt_hostname, self.mqtt_port))
            sys.exit(1)
            
        self.mqtt_client.loop_start()

        timeout = max(0.1,self.tic_interval)
        while True:
            try:
                event = self.event_queue.get(True, timeout) 
                if event[0] == 'message' :
                    self.on_message(event[1])
                elif event[0] == 'connect' :
                    self.on_connect(event[1],event[2],event[3]) 
                elif event[0] == 'disconnect' :
                    self.on_disconnect(event[1],event[2],event[3]) 
                elif event[0] == 'signal' :                
                    self.on_signal(event[1]) 
                else:
                    print('Warning: Unexpected event kind ', kind)
            except queue.Empty as err:
                pass
            except queue.Full as err:
                print(repr(err))            

            if not self.result is None:
                break
                
            now = time.time()
            next_tic = self._last_tic_time + self.tic_interval 
            if now >= next_tic: 
                self._last_tic_time = now 
                self.on_tic()
                timeout = max(0.1, self.tic_interval)
            else:
                timeout = max(0.1 ,next_tic-now)

            if not self.result is None:
                break
            
        self.mqtt_client.loop_stop()
        return self.result

# A base class for clients of Sydpower MQTT
#
# Currently, only works with a LOCAL MQTT server optained by 
# redefining the DNS of mqtt.sydpower.com
#
# TODO: Implement cloud authentication to connect to the real mqtt.sydpower.com
#
class SydpowerApp(SimpleMqttApp):

    def __init__(self, args):
        super().__init__(args)

        self.modbus = SydpowerModbus()
        self.args = args

        if args.mac: 
            self.mac = args.mac.upper()
        else:
            print("Error: no device mac address was specified")
            sys.exit(1)
            
        self.TOPIC_ALL         = self.mac+'/#'
        self.TOPIC_REQUEST     = self.mac+'/client/request/data'
        self.TOPIC_RESPONSE    = self.mac+'/device/response/client/data'
        self.TOPIC_RESPONSE_04 = self.mac+'/device/response/client/04'

    def publish_ReadHoldingRegisters(self, start:int , count:int):
        msg = self.modbus.encode_ReadHoldingRegisters(start, count)
        self.publish(self.TOPIC_REQUEST, msg) 

    def publish_ReadInputRegisters(self, start:int, count:int):
        msg = self.modbus.encode_ReadInputRegisters(start, count)
        self.publish(self.TOPIC_REQUEST, msg) 
        

# Monitor all messages  
class AppMonitor(SydpowerApp):
    
    def __init__(self, args):
        super().__init__(args)
        self.topics = [ self.TOPIC_ALL ] 
        
    def on_connect(self, flags, reason_code, properties):
        for t in self.topics:
            print("# subscribing to "+t)
            self.subscribe(t)
    
    def on_message(self, msg):
        # print("#", msg.topic, msg.payload.hex(), flush=True)
        if msg.topic == self.TOPIC_REQUEST:
            kind = "request"
            func, args, payload, crc = self.modbus.decode(msg.payload,'request', True)
        elif msg.topic == self.TOPIC_RESPONSE:
            kind = "response"
            func, args, payload, crc = self.modbus.decode(msg.payload,'response', True) 
        elif msg.topic == self.TOPIC_RESPONSE_04:            
            kind = "response"
            func, args, payload, crc = self.modbus.decode(msg.payload,'response', True) 
        else:
            print("#", msg.topic, msg.payload.hex(), flush=True)
            return

        if not payload:
            payload_str = ""
        elif type(payload) == list:
            # A list of 16bit values. Display in hex with spaces 
            payload_str = " = [ " + " ".join([ "{:04x}".format(x) for x in payload ]) + " ]"
        elif type(payload) == bytes:
            # Display as a long hexadecimal sequence
            payload_str = " = " + payload.hex()
        else: # should not happen
            payload_str = " = ???????????" 

        print( "{} {}({}){}".format(kind, func,
                                    ",".join([str(x) for x in args]),
                                    payload_str  ) )
 
# Trace changes to registers
class AppTrace(SydpowerApp):
    
    def __init__(self, args):
        super().__init__(args)
        self.topics = [ self.TOPIC_ALL ] 
        self.tic_interval = 2

        self.last_request  = time.time()
        self.last_read_response = "none"
        
        iregs, hregs = parse_register_names( args.target or ["ALL"] )
        
        print("Tracing inputs: ",   " ".join(iregs) ) 
        print("Tracing holdings: ", " ".join(hregs) )

        
        self.iregs = { k: None for k in iregs }
        self.hregs = { k: None for k in hregs }
               
    def on_tic(self):

        if self.args.query:
            #
            # Query input and holding registers at regular interval but
            # not too fast because the device can only process one request
            # at a time.
            #
            if time.time() > self.last_request + 1.0 :
                # Alternate between ReadHoldingRegisters and ReadInputRegisters
                if self.last_read_response == "ReadHoldingRegisters":                    
                    self.publish_ReadInputRegisters(0,IREG_COUNT)
                else:
                    self.publish_ReadHoldingRegisters(0,HREG_COUNT)
        
                   
    def on_connect(self, flags, reason_code, properties):
        for t in self.topics:
            print("# subscribing to "+t)
            self.subscribe(t)
    
    def on_message(self, msg):
        
        if msg.topic == self.TOPIC_REQUEST:
            self.last_request  = time.time()
        elif msg.topic in [ self.TOPIC_RESPONSE , self.TOPIC_RESPONSE_04 ] :
            func, args, payload, crc = self.modbus.decode(msg.payload,'response', False)
            self.trace_response(func,args,payload)
        else:
            pass

    
    def trace_response(self, func: str, args : modbus_values, payload):
        now = timestamp()

        if func=="ReadInputRegisters" :
            self.last_read_response=func
            start = args[0]
            for i in range(args[1]):
                reg = ireg_index_to_name(start+i)
                if reg in self.iregs:
                    old = self.iregs[reg]
                    new = payload[i]
                    if old != new:
                        self.iregs[reg] = new
                        if self.args.timestamp:
                            print(now,'',end='')
                        fmtr=FORMATTER.get(reg,format_dec)
                        print(reg,"=",fmtr(new))

                        
        elif func=="ReadHoldingRegisters":
            self.last_read_response=func
            start = args[0]
            for i in range(args[1]):
                reg = hreg_index_to_name(start+i)
                if reg in self.hregs:
                    old = self.hregs[reg]
                    new = payload[i]
                    if old != new:
                        self.hregs[reg] = new
                        if self.args.timestamp:
                            print(now,'',end='')
                        fmtr=FORMATTER.get(reg,format_dec)
                        print(reg,"=",fmtr(new))



    
def main():
    
    LOGLEVELS=['debug','warn','info','error']
        
    # The MAC address to use for the MQTT topics can be specified by the --mac options
    # or by the SYDPOWER_MAC environment variable.
    # You can also edit the line below and replace None by your device mac address.
    DEFAULT_MAC = os.getenv('SYDPOWER_MAC',None)

    #################### Argument parsing ########################

    parser = argparse.ArgumentParser()

    parser.add_argument('-H', '--hostname' , dest='mqtt_hostname', default="mqtt.sydpower.com" )
    parser.add_argument('-p', '--port'     , dest='mqtt_port', default=1883, type=int)
    parser.add_argument('-u', '--username' , dest='mqtt_username')
    parser.add_argument('-P', '--password' , dest='mqtt_password')
    parser.add_argument('-M', '--mac'      , dest='mac', default=DEFAULT_MAC, help='The device MAC address used as MQTT prefix')
    
    subparsers = parser.add_subparsers(dest='command',required=True)
    
    sub = subparsers.add_parser('monitor', help='Monitor all MQTT messages')

    sub = subparsers.add_parser('trace', help='Trace changes to registers')
    sub.add_argument('-t', '--timestamp', action='store_true',
                     help="prefix each change by a timestamp")
    sub.add_argument('-q', '--query', action='store_true',
                     help="query registers every few seconds")
    
    sub.add_argument('target', metavar='NAME', nargs='*',
                     action='extend',
                     help="a register or register group (default ALL)")
    
    sub = subparsers.add_parser('info', help='Information about the registers (names, ...)')
    
    
    args = parser.parse_args(None)

    ##########################################################

    try:
        
        cmd = args.command
        if cmd in [ "monitor" ] :
            AppMonitor(args).run()
        elif cmd in [ "trace" ] :
            AppTrace(args).run()
        elif cmd in [ "info" ] :
            help_register_names()
            help_iStatusBits()
        else :
            print("ERROR: Unknown command "+cmd)
            sys.exit(-1)

    except KeyboardInterrupt :
        pass

if __name__ == "__main__":
   main()
