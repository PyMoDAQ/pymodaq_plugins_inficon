"""Low-level driver for Inficon STM-2 USB thin film rate/thickness monitors.

Communication uses the SMDP serial protocol (115200 bauds) through the USB/UART bridge of the
unit (Silicon Labs CP210x).
"""
import threading
from typing import Dict, List, Optional

import serial
import serial.tools.list_ports

SILICON_LABS_VID = 0x10C4


def port_from_label(label: str) -> str:
    """Extract the port name from a label such as '123456 (COM3)' or '123456 (/dev/ttyUSB0)'."""
    return label.rsplit('(', 1)[-1].rstrip(')') if label else ''


def make_label(serial_number: str, port: str) -> str:
    """Build the label used in the parameter trees, the inverse of :func:`port_from_label`."""
    return f'{serial_number} ({port})'


def find_stm2(probe: bool = True, timeout: float = 1.0) -> Dict[str, str]:
    """Search the serial ports for STM-2 units.

    Candidates are the ports of Silicon Labs USB/UART bridges. As such bridges are used by many
    other devices, each candidate is queried for its serial number and only the ports answering
    with a valid SMDP frame are kept (unless ``probe`` is False).

    Returns
    -------
    dict
        Maps the port name to the serial number of the STM-2 connected on it. Empty if no STM-2
        is found: no exception is raised so that this can safely be called without hardware.
    """
    found = {}
    for port in serial.tools.list_ports.comports():
        is_silabs = port.vid == SILICON_LABS_VID or (port.manufacturer and "Silicon" in port.manufacturer)
        if not is_silabs:
            continue
        if not probe:
            found[port.device] = ''
            continue
        try:
            with InficonSTM2(port.device, timeout=timeout) as stm2:
                found[port.device] = stm2.get_serial_number()
        except (ConnectionError, ValueError, UnicodeDecodeError):
            continue  # not an STM-2 (or not answering)
    return found


def find_stm2_ports(probe: bool = True) -> List[str]:
    """Names of the ports on which an STM-2 was found, see :func:`find_stm2`."""
    return list(find_stm2(probe))


class SerialBaseSMDP:
    """Implementation of the SMDP frames exchanged with an STM-2 on one serial port.

    The port is opened at the first command and kept open until :meth:`close` is called.
    """

    ADR = [0x22]

    def __init__(self, port: str, timeout: float = 1.0):
        self.port = port
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()

    def open(self) -> None:
        if self._serial is None or not self._serial.is_open:
            try:
                self._serial = serial.Serial(self.port, baudrate=115200, timeout=self.timeout)
            except serial.SerialException as e:
                self._serial = None
                raise ConnectionError(f'Serial error : {e}') from e

    def close(self) -> None:
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                finally:
                    self._serial = None

    def send_command(self, cmd: str) -> str:
        """Send a command and return the data field of the response.

        Raises
        ------
        ConnectionError
            For any communication problem (port, header, checksum, error status of the unit).
        """
        cmd_bytes = bytes(cmd, encoding='utf-8')
        if cmd in ['0', '@', 'P', "'", 'p']:
            cmd_sent = bytes([0x02] + self.ADR) + cmd_bytes + self.checksum(bytes(self.ADR) + cmd_bytes) + bytes([0x0D])
        else:
            cmd_sent = bytes([0x02] + self.ADR + [0x80]) + cmd_bytes + self.checksum(
                bytes(self.ADR + [0x80]) + cmd_bytes) + bytes([0x0D])
        with self._lock:
            try:
                self.open()
                self._serial.reset_input_buffer()
                self._serial.write(cmd_sent)
                resp_bytes = self._serial.read_until(bytes([0x0D]))
            except serial.SerialException as e:
                self._serial = None  # force a new opening at the next command
                raise ConnectionError(f'Serial error : {e}') from e
        return self.check_response(cmd_bytes, resp_bytes)

    def check_response(self, cmd_bytes: bytes, resp_bytes: bytes) -> str:
        if not resp_bytes:
            raise ConnectionError('No response received.')
        header = resp_bytes[:2]
        if not (header == bytes(([0x02] + self.ADR))):
            raise ConnectionError(
                f"Wrong header received : {header}, expected header : {bytes(([0x02] + self.ADR))}.")
        crc = resp_bytes[-3:-1]
        crc_calculated = self.checksum(resp_bytes[1:-3])
        if not crc == crc_calculated:
            raise ConnectionError(
                f"Wrong checksum received : {crc}, checksum calculated with received data : {crc_calculated}.")
        resp_status_bytes = resp_bytes[2]
        self.resp_status(cmd_bytes[0], resp_status_bytes)
        return resp_bytes[3:-3].decode()

    @staticmethod
    def checksum(data: bytes) -> bytes:
        ck = sum(data) % 256
        checksum_1 = (ck >> 4) + 0x30
        checksum_2 = (ck & 0xF) + 0x30
        return bytes((checksum_1, checksum_2))

    @staticmethod
    def resp_status(cmd_byte: int, resp_status_byte: int) -> None:
        """Raise a ConnectionError if the status byte of the response reports an error.

        The status is the difference between the status byte and the command byte. Values above 7
        carry an additional flag of 8 which is removed before the status is checked, so that an
        error is never ignored.
        """
        cmd = chr(cmd_byte)
        error_code = resp_status_byte - cmd_byte
        if error_code > 7:
            error_code -= 8
        if error_code == 1:
            return
        elif error_code == 2:
            raise ConnectionError(f"Illegal command (command code not valid) : {cmd}.")
        elif error_code == 3:
            raise ConnectionError(f"Syntax error (too many bytes in data field, not enough bytes) for command {cmd}.")
        elif error_code == 4:
            raise ConnectionError(f"Data range error for command : {cmd}.")
        elif error_code == 5:
            raise ConnectionError(f"Command {cmd} inhibited.")
        elif error_code == 6:
            raise ConnectionError(f"{cmd} : obsolete command, no action taken.")
        else:
            raise ConnectionError(f"Response status for command : {cmd} not listed : {error_code}.")


class InficonSTM2:
    """One STM-2 unit. Can be used as a context manager, the port is then closed on exit.

    Parameters
    ----------
    port: str, optional
        Serial port of the unit. If None, the first STM-2 found is used.
    timeout: float
        Read timeout of the serial port in seconds.
    """

    def __init__(self, port: Optional[str] = None, timeout: float = 1.0):
        if not port:
            ports = find_stm2_ports()
            if not ports:
                raise ConnectionError("STM-2 not found, check connections and driver installation.")
            port = ports[0]
        self.port = port
        self.protocol = SerialBaseSMDP(port, timeout)

    def close(self) -> None:
        """Close the serial port."""
        self.protocol.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _send(self, cmd: str) -> str:
        return self.protocol.send_command(cmd)

    def get_infos(self):
        """Returns instrument model and firmware version."""
        return self._send('@')

    def get_serial_number(self):
        """Returns instrument serial number."""
        return self._send('@A')

    def get_build_type(self):
        """Returns instrument build type."""
        return self._send('@B')

    def reset_flags(self):
        """Acknowledge "a" response, reset flags so response to 'a' poll is "@" next time."""
        return self._send('L')

    def set_default_parameters(self):
        """Set parameters to default values. Clears memory, reboots module, sets power loss and memloss flags."""
        return self._send('b')

    def reset(self):
        """Cause reset."""
        return self._send('d')

    def get_firmware_crc(self):
        """Queries firmware version CRC as a decimal value."""
        return self._send('p')

    def set_timer_thickness_zeroes(self):
        """Zeroes timer and thickness."""
        return self._send('B')

    def set_thickness_zeroes(self):
        """Zeroes thickness."""
        return self._send('D')

    def set_timer_zeroes(self):
        """Zeroes timer."""
        return self._send('C')

    def set_film_name(self, name):
        """Sets the current film name to 'name'."""
        if not len(name) < 9:
            raise ValueError(f"Names should have 8 or less characters, name entered : {name}, length : {len(name)}.")
        return self._send('q=' + name)

    def get_film_name(self) -> str:
        """Returns current film name."""
        return self._send('q?')

    def set_film_density(self, density):
        """Sets current film density to 'density'."""
        if not 0.40 <= density <= 99.99:
            raise ValueError(f"Density value should be between 0.40 and 99.99; value entered : {density}.")
        return self._send('E=' + str(density))

    def get_film_density(self) -> float:
        """Returns current film density."""
        return float(self._send('E?'))

    def set_film_zratio(self, zratio):
        """Sets current film Z-ratio to 'Zratio'."""
        if not 0.100 <= zratio <= 9.999:
            raise ValueError(f"Z-ratio value should be between 0.100 and 9.999; value entered : {zratio}.")
        return self._send('F=' + str(zratio))

    def get_film_zratio(self) -> float:
        """Returns current film Z-ratio."""
        return float(self._send('F?'))

    def set_film_tooling(self, filmtooling):
        """Set current film tooling to 'FilmTooling'."""
        if not 10.0 <= filmtooling <= 999.9:
            raise ValueError(
                f"Film tooling value should be between 10.0 and 999.9; value entered : {filmtooling}.")
        return self._send('J=' + str(filmtooling))

    def get_film_tooling(self) -> float:
        """Returns current film tooling."""
        return float(self._send('J?'))

    def set_samples_number(self, number):
        """Sets number of samples to 'number' for temporal averaging."""
        if not 1 <= number <= 50:
            raise ValueError(f"Samples number value should be between 1 and 50; value entered : {number}.")
        return self._send('r=' + str(number))

    def get_samples_number(self) -> int:
        """Returns current sample number."""
        return int(float(self._send('r?')))

    def get_cristal_status(self):
        """Return crystal fail status : @ = crystal good, ! = crystal failed."""
        status = self._send('M')
        if status == '@':
            return 'crystal good'
        elif status == '!':
            return 'crystal failed'
        else:
            return status

    def get_thickness(self):
        """Return thickness value."""
        return float(self._send('S'))

    def get_film_mass(self):
        """Return film mass."""
        return float(self._send('s'))

    def get_rate(self):
        """Return rate."""
        return float(self._send('T'))

    def get_mass_accumulation_rate(self):
        """Return mass accumulation rate in μg/ (*s/cm²)."""
        return float(self._send('t'))

    def get_frequency(self):
        """Return sensor frequency."""
        return float(self._send('U'))

    def get_cristal_life(self):
        """Return crystal life."""
        return self._send('V')

    def get_timer(self) -> str:
        """Return timer in H:MM:SS format."""
        return self._send('W')

    def get_reset_status(self) -> str:
        """Return RESET Status : @ = OK, A = lost power, D = lost NONV memory, E = lost power and NONV memory."""
        return self._send('a')
