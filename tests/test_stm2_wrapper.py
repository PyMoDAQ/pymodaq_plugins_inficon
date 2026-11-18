"""Tests of the STM-2 driver with a simulated serial port: no hardware is needed."""
from types import SimpleNamespace

import pytest
import serial

from pymodaq_plugins_inficon.hardware import stm2
from pymodaq_plugins_inficon.hardware.stm2 import (InficonSTM2, SerialBaseSMDP, find_stm2, make_label,
                                                   port_from_label)

ADR = SerialBaseSMDP.ADR[0]


def frame(cmd: str, data: str = '', status_offset: int = 1, address: int = ADR) -> bytes:
    """Build a response frame of the unit to the command `cmd`."""
    body = bytes([address, ord(cmd[0]) + status_offset]) + data.encode()
    return bytes([0x02]) + body + SerialBaseSMDP.checksum(body) + bytes([0x0D])


class FakeSerial:
    """Minimal replacement of serial.Serial answering with the data of `replies` (command -> data)."""
    instances = []
    replies = {}
    status_offset = 1
    fail_on_open = False

    def __init__(self, port, baudrate=9600, timeout=None):
        if FakeSerial.fail_on_open:
            raise serial.SerialException(f'could not open {port}')
        self.port = port
        self.is_open = True
        self.written = []
        self._response = b''
        FakeSerial.instances.append(self)

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written.append(data)
        cmd = data[2:-3].decode() if data[2] != 0x80 else data[3:-3].decode()
        if cmd in FakeSerial.replies:
            reply = FakeSerial.replies[cmd]
            if callable(reply):  # the reply depends on the port (several units)
                reply = reply(self.port)
            self._response = frame(cmd, reply, FakeSerial.status_offset)
        else:
            self._response = b''

    def read_until(self, terminator):
        return self._response

    def close(self):
        self.is_open = False


@pytest.fixture
def fake_serial(monkeypatch):
    FakeSerial.instances = []
    FakeSerial.replies = {'@A': '123456', 'S': '12.5', 'U': '5999000.0', 'q?': 'film', 'E?': '2.70', 'r?': '5'}
    FakeSerial.status_offset = 1
    FakeSerial.fail_on_open = False
    monkeypatch.setattr(stm2.serial, 'Serial', FakeSerial)
    return FakeSerial


def test_checksum():
    assert SerialBaseSMDP.checksum(bytes([0x22, 0x40])) == bytes((((0x62 >> 4) + 0x30), (0x62 & 0xF) + 0x30))


def test_labels():
    assert port_from_label(make_label('123456', 'COM12')) == 'COM12'
    assert port_from_label(make_label('123456', '/dev/ttyUSB0')) == '/dev/ttyUSB0'
    assert port_from_label('') == ''


def test_read_values(fake_serial):
    with InficonSTM2('COM3') as unit:
        assert unit.get_serial_number() == '123456'
        assert unit.get_thickness() == 12.5
        assert unit.get_frequency() == 5999000.0
        assert unit.get_film_density() == 2.7
        assert unit.get_samples_number() == 5


def test_port_is_kept_open_and_closed_on_exit(fake_serial):
    with InficonSTM2('COM3') as unit:
        unit.get_thickness()
        unit.get_frequency()
        assert len(fake_serial.instances) == 1  # one opening for several commands
        assert fake_serial.instances[0].is_open
    assert not fake_serial.instances[0].is_open


def test_set_commands_are_validated(fake_serial):
    with InficonSTM2('COM3') as unit:
        with pytest.raises(ValueError):
            unit.set_film_density(1000)
        with pytest.raises(ValueError):
            unit.set_film_name('way too long name')
        with pytest.raises(ValueError):
            unit.set_samples_number(0)


def test_no_response(fake_serial):
    with InficonSTM2('COM3') as unit:
        with pytest.raises(ConnectionError, match='No response'):
            unit.get_build_type()  # no reply defined for this command


def test_wrong_checksum(fake_serial):
    proto = SerialBaseSMDP('COM3')
    resp = bytearray(frame('S', '1.0'))
    resp[-2] ^= 0x01
    with pytest.raises(ConnectionError, match='checksum'):
        proto.check_response(b'S', bytes(resp))


def test_wrong_header(fake_serial):
    proto = SerialBaseSMDP('COM3')
    with pytest.raises(ConnectionError, match='header'):
        proto.check_response(b'S', frame('S', '1.0', address=0x23))


@pytest.mark.parametrize('offset, message', [(2, 'Illegal command'), (3, 'Syntax error'), (4, 'Data range'),
                                             (5, 'inhibited'), (6, 'obsolete'), (7, 'not listed')])
def test_error_status(fake_serial, offset, message):
    FakeSerial.status_offset = offset
    with InficonSTM2('COM3') as unit:
        with pytest.raises(ConnectionError, match=message):
            unit.get_thickness()


@pytest.mark.parametrize('offset, message', [(10, 'Illegal command'), (12, 'Data range')])
def test_error_status_with_flag_is_not_ignored(fake_serial, offset, message):
    """A status above 7 carries a flag of 8: the error code left must still be checked."""
    FakeSerial.status_offset = offset
    with InficonSTM2('COM3') as unit:
        with pytest.raises(ConnectionError, match=message):
            unit.get_thickness()


def test_status_with_flag_and_no_error(fake_serial):
    FakeSerial.status_offset = 9
    with InficonSTM2('COM3') as unit:
        assert unit.get_thickness() == 12.5


def test_serial_error_is_a_connection_error(fake_serial):
    FakeSerial.fail_on_open = True
    unit = InficonSTM2('COM3')
    with pytest.raises(ConnectionError, match='Serial error'):
        unit.get_thickness()


def test_error_types_are_kept(fake_serial):
    FakeSerial.replies['S'] = 'not a number'
    with InficonSTM2('COM3') as unit:
        with pytest.raises(ValueError):  # not turned into a bare Exception
            unit.get_thickness()


def fake_ports(*ports):
    return lambda: [SimpleNamespace(device=dev, vid=vid, manufacturer=manufacturer)
                    for dev, vid, manufacturer in ports]


def test_find_stm2_keeps_only_answering_silabs_ports(fake_serial, monkeypatch):
    monkeypatch.setattr(stm2.serial.tools.list_ports, 'comports',
                        fake_ports(('COM3', 0x10C4, 'Silicon Labs'),
                                   ('COM4', 0x0403, 'FTDI'),
                                   ('COM5', None, 'Silicon Labs')))
    original_write = FakeSerial.write

    def silent_on_com5(self, data):
        original_write(self, data)
        if self.port == 'COM5':
            self._response = b''  # another CP210x device, which does not speak SMDP

    monkeypatch.setattr(FakeSerial, 'write', silent_on_com5)
    assert find_stm2() == {'COM3': '123456'}
    assert find_stm2(probe=False) == {'COM3': '', 'COM5': ''}


def test_find_stm2_without_hardware_does_not_raise(monkeypatch):
    monkeypatch.setattr(stm2.serial.tools.list_ports, 'comports', fake_ports())
    assert find_stm2() == {}


def test_default_port_requires_a_unit(monkeypatch):
    monkeypatch.setattr(stm2.serial.tools.list_ports, 'comports', fake_ports())
    with pytest.raises(ConnectionError, match='not found'):
        InficonSTM2()
