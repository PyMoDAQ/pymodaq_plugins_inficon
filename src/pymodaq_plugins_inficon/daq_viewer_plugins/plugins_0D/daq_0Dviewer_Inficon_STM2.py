import numpy as np

from pymodaq_utils.utils import ThreadCommand
from pymodaq_utils.logger import set_logger, get_module_name
from pymodaq_data.data import DataToExport
from pymodaq_gui.parameter import Parameter

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_inficon.hardware.stm2 import InficonSTM2, find_stm2, make_label, port_from_label

logger = set_logger(get_module_name(__file__))


class DAQ_0DViewer_Inficon_STM2(DAQ_Viewer_base):
    """
    Developed and tested for STM-2 instrument.
    Developed and tested with Python 3.12
    Tested with PyMoDAQ 5.2 and 5.3
    Requires installation of the following drivers:
        SMDP protocol server
        USB installer
        STM-2 Application software
    They are all available in the Download section of the Inficon STM-2 web page:
        https://www.inficon.com/en/products/thin-film-technology/thickness-monitor-stm-2-usb-thin-film-rate
    Another USB driver may be required for the STM-2 to be detected by the computer:
        CP210x Windows Drivers from Silicon Labs: https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers?tab=downloads
    pyserial package is also required.

    The STM-2 units are searched when the detector is initialized (no hardware is needed to create
    the module). Averaging of several grabs is done by PyMoDAQ (Naverage); the averaging done by the
    unit itself is set with the 'Samples number' parameter.
    """
    hardware_averaging = False

    # (data name, label, unit, getter of the controller)
    _channels = (('STM-2 Frequency', 'Frequency', 'Hz', 'get_frequency'),
                 ('STM-2 Thickness', 'Thickness', 'Å', 'get_thickness'),
                 ('STM-2 Rate', 'Rate', 'Å/s', 'get_rate'))

    params = comon_parameters + [
        {'title': 'Device serial number :', 'name': 'device_serial_number', 'type': 'list'},
        {'title': 'Refresh COM ports :', 'name': 'refresh_ports', 'type': 'bool_push'},
        {'title': 'Device information :', 'name': 'device_info', 'type': 'str', 'value': '', 'readonly': True},
        {'title': 'Crystal status :', 'name': 'crystal_status', 'type': 'str', 'value': '', 'readonly': True},
        {'title': 'Zero thickness and timer on connection :', 'name': 'zero_on_connect', 'type': 'bool',
         'value': False},
        {'title': 'Zero thickness and timer :', 'name': 'set_timer_thickness_zeroes', 'type': 'bool_push'},
        {'title': 'Film name :', 'name': 'film_name', 'type': 'str'},
        {'title': 'Film density :', 'name': 'film_density', 'type': 'float', 'max': 99.99, 'min': 0.40},
        {'title': 'Film Z-ratio :', 'name': 'film_zratio', 'type': 'float', 'max': 9.999, 'min': 0.100},
        {'title': 'Samples number :', 'name': 'samples_number', 'type': 'int', 'max': 50, 'min': 1, 'value': 5}
    ]

    def ini_attributes(self):
        # no hardware access here: the module must be creatable without any STM-2 connected
        self.controller: InficonSTM2 = None
        self.port = None

    def _report_error(self, message: str):
        logger.error(message)
        self.emit_status(ThreadCommand('Update_Status', [message, 'log']))

    def refresh_ports(self) -> list:
        """Scan the serial ports and update the list of available STM-2 (serial number and port)."""
        labels = [make_label(sn, port) for port, sn in find_stm2().items()]
        with self.settings.treeChangeBlocker():
            self.settings.child('device_serial_number').setLimits(labels)
        self.emit_status(ThreadCommand('Update_Status', [f'Detected STM-2 : {labels}', 'log']))
        return labels

    def connect_to(self, port: str):
        """Close the current connection (if any) and connect the STM-2 found on `port`."""
        self.close_controller()
        controller = InficonSTM2(port)
        try:
            controller.get_infos()  # checks that an STM-2 really answers
        except Exception:
            controller.close()
            raise
        self.controller = controller
        self.port = port

    def close_controller(self):
        if self.controller is not None:
            self.controller.close()
        self.controller = None

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            Device serial number : list of detected STM-2 monitors, can be selected during initialization
            (changes may occur between units, see red light on it).
            Refresh COM ports : scan again the serial ports.
            Zero thickness and timer : as in title.
            Film name : sets unit film name (8 characters max), nice to remember who is who.
            Film density : sets film density on the unit for calculated values.
            Film Z-ratio : sets film Z-ratio on the unit for calculated values.
            Samples number : sets sample number on the unit for calculated values.
        """
        name = param.name()
        try:
            if name == 'refresh_ports':
                if param.value():
                    try:
                        self.refresh_ports()
                    finally:
                        param.setValue(False)
                return
            if self.controller is None:
                return  # not initialized yet, settings are read from the unit at initialization
            if name == 'device_serial_number':
                port = port_from_label(param.value())
                if port and port != self.port:
                    self.connect_to(port)
                    self.emit_status(ThreadCommand('Update_Status', [f"Selected port is now : {self.port}", 'log']))
            elif name == 'set_timer_thickness_zeroes':
                if param.value():  # a bool_push goes back to False after the action, nothing to do then
                    try:
                        self.controller.set_timer_thickness_zeroes()
                    finally:
                        param.setValue(False)
            elif name == 'film_name':
                self.controller.set_film_name(param.value())
            elif name == 'film_density':
                self.controller.set_film_density(param.value())
            elif name == 'film_zratio':
                self.controller.set_film_zratio(param.value())
            elif name == 'samples_number':
                self.controller.set_samples_number(param.value())
            else:
                return
            self.update_parameter_branch()
        except Exception as e:
            logger.exception(f'Could not apply the setting {name}')
            self._report_error(f'Could not apply the setting {name} : {e}')

    def update_parameter_branch(self):
        """Read the state of the unit and show it in the parameter tree, without triggering commit_settings."""
        infos = ('Model and firmware version : {}, Build type : {}, Firmware CRC : {}, Reset Status : {}'.format
                 (self.controller.get_infos(), self.controller.get_build_type(), self.controller.get_firmware_crc(),
                  self.controller.get_reset_status()))
        with self.settings.treeChangeBlocker():
            self.settings.child('device_info').setValue(infos)
            self.settings.child('crystal_status').setValue(self.controller.get_cristal_status())
            self.settings.child('film_name').setValue(str(self.controller.get_film_name()))
            self.settings.child('film_density').setValue(float(self.controller.get_film_density()))
            self.settings.child('film_zratio').setValue(float(self.controller.get_film_zratio()))
            self.settings.child('samples_number').setValue(int(self.controller.get_samples_number()))

    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """
        try:
            if self.is_master:
                labels = self.refresh_ports()
                if not labels:
                    raise ConnectionError("STM-2 not found, check connections and driver installation.")
                selected = self.settings.child('device_serial_number').value()
                if selected not in labels:
                    selected = labels[0]
                with self.settings.treeChangeBlocker():
                    self.settings.child('device_serial_number').setValue(selected)
                self.connect_to(port_from_label(selected))
            else:
                self.controller = controller

            if self.settings.child('zero_on_connect').value():
                self.controller.set_timer_thickness_zeroes()
            self.update_parameter_branch()
        except Exception as e:
            logger.exception('STM-2 initialization failed')
            self._report_error(f'STM-2 initialization failed : {e}')
            return f'STM-2 initialization failed : {e}', False

        self.dte_signal_temp.emit(DataToExport('STM-2 Data',
                                               data=[DataFromPlugins(name=name, data=[np.array([0.0])],
                                                                     dim='Data0D', labels=[label], units=unit)
                                                     for name, label, unit, _ in self._channels]))
        info = "Default values for selected STM-2 should be printed and graphs should appear."
        return info, True

    def close(self):
        """Terminate the communication protocol"""
        if self.is_master:
            self.close_controller()
        else:
            self.controller = None

    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Not used: hardware averaging is not implemented (hardware_averaging is False), PyMoDAQ
            averages the grabs itself. See the 'Samples number' parameter for the averaging done by the unit.
        kwargs: dict
            others optionals arguments
        """
        self.dte_signal.emit(DataToExport('STM-2 Data',
                                          data=[DataFromPlugins(name=name,
                                                                data=[np.array([getattr(self.controller, getter)()])],
                                                                dim='Data0D', labels=[label], units=unit)
                                                for name, label, unit, getter in self._channels]))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        self.emit_status(ThreadCommand('Update_Status', ['Stopped']))
        return ''


if __name__ == '__main__':
    main(__file__)
