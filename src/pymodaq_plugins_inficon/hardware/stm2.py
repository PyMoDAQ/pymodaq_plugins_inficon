import serial.tools.list_ports

SILICON_LABS_VID = 0x10C4  # USB vendor id of Silicon Labs (CP210x USB/UART bridges)

def find_stm2_ports(probe: bool = True) -> list:
    """Names of the serial ports on which an STM-2 is connected. Never raises."""
    ports = []
    for port in serial.tools.list_ports.comports():
        if port.vid == SILICON_LABS_VID or (port.manufacturer and "Silicon" in port.manufacturer):
            if probe:
                try:
                    InficonSTM2(port.device).get_serial_number()
                except Exception:
                    continue  # not an STM-2, or not answering
            ports.append(port.device)
    return ports

class SerialBaseSMDP :

    ADR = [0x22]

    def __init__(self):
        self.stm2_ports = []

    def search_stm2_ports(self) -> None:
        """Searches for STM-2 in the COM ports of the computer. Fills the stm2_ports list attribute."""
        self.stm2_ports = find_stm2_ports()
        if not self.stm2_ports:
            raise ConnectionError("STM-2 not found, check connections and driver installation.")

    def send_command(self, port, cmd):
        cmd_bytes = bytes(cmd, encoding='utf-8')
        if cmd in ['0', '@', 'P', "'", 'p']:
            cmd_sent = bytes([0x02] + self.ADR) + cmd_bytes + self.checksum(bytes(self.ADR) + cmd_bytes) + bytes([0x0D])
        else:
            cmd_sent = bytes([0x02] + self.ADR + [0x80]) + cmd_bytes + self.checksum(bytes(self.ADR + [0x80]) + cmd_bytes) + bytes([0x0D])
        try:
            with serial.Serial(port, baudrate=115200, timeout=1) as s:
                s.write(cmd_sent)
                resp_bytes = s.read_until(bytes([0x0D]))
                return self.check_response(cmd_bytes, resp_bytes)
        except serial.SerialException as e:
            raise ConnectionError(f'Serial error : {e}') from e
        except Exception:
            raise

    def check_response(self, cmd_bytes, resp_bytes) :
        if resp_bytes:
            header = resp_bytes[:2]
            if not (header == bytes(([0x02] + self.ADR))):
                raise ConnectionError(f"Wrong header received : {header}, expected header : {bytes(([0x02] + self.ADR))}.")
            crc = resp_bytes[-3:-1]
            crc_calculated = self.checksum(resp_bytes[1:-3])
            if not crc == crc_calculated:
                raise ConnectionError(f"Wrong checksum received : {crc}, checksum calculated with received data : {crc_calculated}.")
            resp_status_bytes = resp_bytes[2]
            self.resp_status(cmd_bytes[0], resp_status_bytes)
            return resp_bytes[3:-3].decode()
        else:
            raise ConnectionError('No response received.')

    @staticmethod
    def checksum(data):
        ck = sum(data) % 256
        checksum_1 = (ck >> 4) + 0x30
        checksum_2 = (ck & 0xF) + 0x30
        return bytes((checksum_1, checksum_2))

    @staticmethod
    def resp_status(cmd_bytes, resp_status_bytes):
        """Returns True if the power-fail flag (bit D3) is set. Status = bits D2-D0."""
        cmd = chr(cmd_bytes)
        error_code = resp_status_bytes & 0x07
        power_fail = bool(resp_status_bytes & 0x08)
        if error_code == 1:
            pass
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
        return power_fail
class InficonSTM2:

    def __init__(self, port=None):
        self.protocol = SerialBaseSMDP()
        if not port:
            self.protocol.search_stm2_ports()
            self.stm2_ports = self.protocol.stm2_ports
            self.port = self.stm2_ports[0]  # Prend le premier port trouvé par défaut
        else:
            self.port = port

    def get_infos(self):
        """Returns instrument model and firmware version."""
        return self.protocol.send_command(self.port, '@')

    def get_serial_number(self):
        """Returns instrument serial number."""
        return self.protocol.send_command(self.port, '@A')

    def get_build_type(self):
        """Returns instrument build type."""
        return self.protocol.send_command(self.port, '@B')

    def reset_flags(self):
        """Acknowledge "a" response, reset flags so response to 'a' poll is "@" next time."""
        return self.protocol.send_command(self.port, 'L')

    def set_default_parameters(self):
        """Set parameters to default values. Clears memory, reboots module, sets power loss and memloss flags."""
        return self.protocol.send_command(self.port, 'b')

    def reset(self):
        """Cause reset."""
        return self.protocol.send_command(self.port, 'd')

    def get_firmware_crc(self):
        """Queries firmware version CRC as a decimal value."""
        return self.protocol.send_command(self.port, 'p')

    def set_timer_thickness_zeroes(self):
        """Zeroes timer and thickness."""
        return self.protocol.send_command(self.port, 'B')

    def set_thickness_zeroes(self):
        """Zeroes thickness."""
        return self.protocol.send_command(self.port, 'D')

    def set_timer_zeroes(self):
        """Zeroes timer."""
        return self.protocol.send_command(self.port, 'C')

    def set_film_name(self, name):
        """Sets the current film name to 'name'."""
        if not len(name) < 9:
            raise ValueError(f"Names should have 8 or less characters, name entered : {name}, length : {len(name)}.")
        return self.protocol.send_command(self.port, 'q=' + name)

    def get_film_name(self):
        """Returns current film name."""
        return self.protocol.send_command(self.port, 'q?')

    def set_film_density(self, density):
        """Sets current film density to 'density'."""
        if not 0.40 <= density <= 99.99:
            raise ValueError(f"Density value should be between 0.40 and 99.99; value entered : {density}.")
        return self.protocol.send_command(self.port, 'E=' + str(density))

    def get_film_density(self):
        """Returns current film density."""
        return self.protocol.send_command(self.port, 'E?')

    def set_film_zratio(self, zratio):
        """Sets current film Z-ratio to 'Zratio'."""
        if not 0.100 <= zratio <= 9.999:
            raise ValueError(f"Z-ratio value should be between 0.100 and 9.999; value entered : {zratio}.")
        return self.protocol.send_command(self.port, 'F=' + str(zratio))

    def get_film_zratio(self):
        """Returns current film Z-ratio."""
        return self.protocol.send_command(self.port, 'F?')

    def set_film_tooling(self, filmtooling):
        """Set current film tooling to 'FilmTooling'."""
        if not 10.0 <= filmtooling <= 999.9:
            raise ValueError(
                f"Film tooling value should be between 10.0 and 999.9; value entered : {filmtooling}.")
        return self.protocol.send_command(self.port, 'J=' + str(filmtooling))

    def get_film_tooling(self) -> str:
        """Returns current film tooling."""
        return self.protocol.send_command(self.port, 'J?')

    def set_samples_number(self, number):
        """Sets number of samples to 'number' for temporal averaging."""
        if not 1 <= number <= 50:
            raise ValueError(f"Samples number value should be between 1 and 50; value entered : {number}.")
        return self.protocol.send_command(self.port, 'r=' + str(number))

    def get_samples_number(self):
        """Returns current sample number."""
        return self.protocol.send_command(self.port, 'r?')

    def get_cristal_status(self):
        """Return crystal fail status : @ = crystal good, ! = crystal failed."""
        status = self.protocol.send_command(self.port, 'M')
        if status == '@':
            return 'crystal good'
        elif status == '!':
            return 'crystal failed'
        else :
            return status

    def get_thickness(self):
        """Return thickness value."""
        return float(self.protocol.send_command(self.port, 'S'))

    def get_film_mass(self):
        """Return film mass."""
        return float(self.protocol.send_command(self.port, 's'))

    def get_rate(self):
        """Return rate."""
        return float(self.protocol.send_command(self.port, 'T'))

    def get_mass_accumulation_rate(self):
        """Return mass accumulation rate in μg/ (*s/cm²)."""
        return float(self.protocol.send_command(self.port, 't'))

    def get_frequency(self):
        """Return sensor frequency."""
        return float(self.protocol.send_command(self.port, 'U'))

    def get_cristal_life(self):
        """Return crystal life."""
        return self.protocol.send_command(self.port, 'V')

    def get_timer(self) -> str:
        """Return timer in H:MM:SS format."""
        return self.protocol.send_command(self.port, 'W')

    def get_reset_status(self) -> str:
        """Return RESET Status : @ = OK, A = lost power, D = lost NONV memory, E = lost power and NONV memory."""
        return self.protocol.send_command(self.port, 'a')