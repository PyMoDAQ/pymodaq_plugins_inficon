import numpy as np

from pymodaq_utils.utils import ThreadCommand
from pymodaq_utils.logger import set_logger, get_module_name
from pymodaq_data.data import DataToExport
from pymodaq_gui.parameter import Parameter
from pymodaq_gui.parameter.pymodaq_ptypes import GroupParameter, registerParameterType

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_inficon.hardware.stm2 import InficonSTM2, find_stm2, make_label, port_from_label

logger = set_logger(get_module_name(__file__))


qcm_params = [
    {'title': 'Device serial number :', 'name': 'device_serial_number', 'type': 'list'},
    {'title': 'Crystal status :', 'name': 'crystal_status', 'type': 'str', 'value': '', 'readonly': True},
]


class STM2ScalableGroup(GroupParameter):
    """Group parameter allowing the user to add/remove QCM_XX entries at runtime, each holding
    its own copy of qcm_params (device_serial_number, crystal_status)."""

    def __init__(self, **opts):
        opts['type'] = 'group'
        opts['addText'] = 'Add QCM'
        super().__init__(**opts)

    def addNew(self):
        indexes = [int(child.name().split('_')[1]) for child in self.children()
                   if child.name().startswith('qcm_')]
        new_index = max(indexes) + 1 if indexes else max(len(self.children()), 1)
        children = [{**p} for p in qcm_params]  # fresh copy, don't share dicts between QCMs
        self.addChild({
            'title': f'QCM {new_index}',
            'name': f'qcm_{new_index}',
            'type': 'bool',
            'value': True,
            'removable': True,
            'renamable': False,
            'children': children,
        })


registerParameterType('groupstm2', STM2ScalableGroup, override=True)


class DAQ_0DViewer_Inficon_STM2_Multi(DAQ_Viewer_base):
    """ Instrument plugin class for a OD viewer managing a variable number of Inficon STM-2 units.
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

    Units are added/removed at runtime from the 'activated_stm2' group parameter (like in Mock
    plugin). Film settings (name/density/z ratio/samples) and the zero-thickness command are
    broadcast to every currently connected unit; each unit keeps its own serial number selection
    and crystal status readout. Each checked channel (frequency/thickness/thickness_rate) opens
    its own window, plotting every connected unit as a separate curve within it. To add more
    checkable channels (film mass for instance) one have to edit this code.

    The STM-2 units are searched when the detector is initialized (no hardware is needed to create
    the module). At initialization, the QCM entries without a serial number are given the detected
    units that are not selected yet. Averaging of several grabs is done by PyMoDAQ (Naverage); the
    averaging done by each unit is set with the 'Samples number' parameter.

    Attributes
    -----------
    controllers: dict[str, InficonSTM2]
        Maps a QCM group child name ('qcm_1', 'qcm_2', ...) to its open InficonSTM2 connection.
    """
    hardware_averaging = False

    N_QCM = 4 #Number of STM2 controllers
    params = comon_parameters + [
        {'title': 'Selected channel :', 'name': 'channel', 'type': 'group', 'children': [
            {'title': 'Frequency (Hz)', 'name': 'frequency', 'type': 'bool', 'value': True},
            {'title': 'Thickness (Å)', 'name': 'thickness', 'type': 'bool', 'value': True},
            {'title': 'Thickness growth rate (Å/s)', 'name': 'thickness_rate', 'type': 'bool', 'value': True},
        ]},
        {'title': 'Refresh COM ports :', 'name': 'refresh_ports', 'type': 'bool_push'},
        {'title': 'Zero thickness and timer on connection :', 'name': 'zero_on_connect', 'type': 'bool',
         'value': False},
        {'title': 'Zero thickness and timer :', 'name': 'set_timer_thickness_zeroes', 'type': 'bool_push'},
        {'title': 'Film name :', 'name': 'film_name', 'type': 'str'},
        {'title': 'Film density :', 'name': 'film_density', 'type': 'float', 'max': 99.99, 'min': 0.40},
        {'title': 'Film Z-ratio :', 'name': 'film_zratio', 'type': 'float', 'max': 9.999, 'min': 0.100},
        {'title': 'Samples number :', 'name': 'samples_number', 'type': 'int', 'max': 50, 'min': 1, 'value': 5},
        {'title': 'Activated STM-2', 'name': 'activated_stm2', 'type': 'groupstm2', 'children': [
            {'title': f'QCM {i}', 'name': f'qcm_{i}', 'type': 'bool', 'value': True, 'removable': True,
             'renamable': False, 'children': [{**p} for p in qcm_params]}
            for i in range (1, N_QCM+1)
        ]},
    ]

    _channel_getters = {
        'frequency': ('get_frequency', 'Hz'),
        'thickness': ('get_thickness', 'Å'),
        'thickness_rate': ('get_rate', 'Å/s'),
    }

    def _active_channels(self):
        """Names of the currently checked channel booleans, in tree order."""
        return [ch.name() for ch in self.settings.child('channel').children() if ch.value()]

    @staticmethod
    def _port_from_label(label: str) -> str:
        return port_from_label(label)

    def _report_error(self, message: str):
        logger.error(message)
        self.emit_status(ThreadCommand('Update_Status', [message, 'log']))

    def ini_attributes(self):
        # no hardware access here: the module must be creatable without any STM-2 connected
        self.controllers: dict = {}      # QCM name -> connected InficonSTM2
        self._ports_in_use: dict = {}    # QCM name -> port currently connected
        self.stm2_ports: list = []

    def refresh_available_ports(self) -> list:
        """Scan the serial ports and update every QCM's device_serial_number choices, keeping the
        currently selected value if it is still valid. Returns the labels of the detected units."""
        found = find_stm2()
        self.stm2_ports = list(found)
        labels = [make_label(sn, port) for port, sn in found.items()]

        with self.settings.treeChangeBlocker():
            for qcm in self.settings.child('activated_stm2').children():
                sn_child = qcm.child('device_serial_number')
                current = sn_child.value()
                sn_child.setLimits(labels)
                if current in labels:
                    sn_child.setValue(current)

        self.emit_status(ThreadCommand('Update_Status', [f'Detected STM-2 : {labels}', 'log']))
        return labels

    def assign_free_units(self, labels: list):
        """Give each activated QCM without a valid serial number a detected unit not selected yet."""
        qcms = self.settings.child('activated_stm2').children()
        used = {qcm.child('device_serial_number').value() for qcm in qcms}
        free = [label for label in labels if label not in used]
        with self.settings.treeChangeBlocker():
            for qcm in qcms:
                sn_child = qcm.child('device_serial_number')
                if qcm.value() and sn_child.value() not in labels and free:
                    sn_child.setValue(free.pop(0))

    def sync_controllers(self):
        """Rebuild self.controllers from the current parameter tree: connect any activated QCM
        with a chosen serial number that isn't connected yet (or whose port changed), and
        disconnect any QCM that got deactivated, removed, or emptied of its port choice."""
        active = {}
        for qcm in self.settings.child('activated_stm2').children():
            name = qcm.name()
            if not qcm.value():  # unchecked
                continue
            label = qcm.child('device_serial_number').value()
            port = self._port_from_label(label)
            if not port:
                continue
            active[name] = port

        # disconnect what is not active anymore
        for name in list(self.controllers.keys()):
            if name not in active or self._ports_in_use.get(name) != active[name]:
                self.controllers.pop(name).close()
                self._ports_in_use.pop(name, None)

        # connect what changed
        zero = self.settings.child('zero_on_connect').value()
        for name, port in active.items():
            if name not in self.controllers:
                try:
                    ctrl = InficonSTM2(port)
                    try:
                        if zero:
                            ctrl.set_timer_thickness_zeroes()
                        status = ctrl.get_cristal_status()  # also checks that the unit answers
                    except Exception:
                        ctrl.close()
                        raise
                    self.controllers[name] = ctrl
                    self._ports_in_use[name] = port
                    with self.settings.treeChangeBlocker():
                        self.settings.child('activated_stm2', name, 'crystal_status').setValue(status)
                except Exception as e:
                    logger.exception(f'Could not connect {name}')
                    self._report_error(f'Could not connect {name} : {e}')

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings.

        Almost every change (activation toggle, serial number choice, QCM added/removed) is
        handled uniformly by resynchronising self.controllers with the parameter tree via
        sync_controllers(), exactly like set_Mock_data() rebuilds the Mock plugin's data from its
        tree on every commit. Only the genuinely "broadcast" commands (film settings, zeroing,
        port refresh) need an explicit branch.

        Parameters
        ----------
        param: Parameter
            channel : checkbox to chose which channel (frequency/thickness/thickness_rate) to plot during grab data.
            refresh_ports : relaunch port/serial number detection for available units
            zero_on_connect : zero thickness and timer each time a unit gets connected
            set_timer_thickness_zeroes : zero thickness and timer for all connected controllers
            film_name / film_density / film_zratio / samples_number : the same for all controllers
            device_serial_number managed by sync_controllers() method
        """
        name = param.name()
        try:
            if name == 'refresh_ports':
                if param.value():
                    try:
                        self.refresh_available_ports()
                    finally:
                        param.setValue(False)
                return

            self.sync_controllers()

            if name == 'set_timer_thickness_zeroes':
                if param.value():  # a bool_push goes back to False after the action, nothing to do then
                    try:
                        for ctrl in self.controllers.values():
                            ctrl.set_timer_thickness_zeroes()
                    finally:
                        param.setValue(False)
            elif name == 'film_name':
                for ctrl in self.controllers.values():
                    ctrl.set_film_name(param.value())
            elif name == 'film_density':
                for ctrl in self.controllers.values():
                    ctrl.set_film_density(param.value())
            elif name == 'film_zratio':
                for ctrl in self.controllers.values():
                    ctrl.set_film_zratio(param.value())
            elif name == 'samples_number':
                for ctrl in self.controllers.values():
                    ctrl.set_samples_number(param.value())
        except Exception as e:
            logger.exception(f'Could not apply the setting {name}')
            self._report_error(f'Could not apply the setting {name} : {e}')

    def ini_detector(self, controller=None):
        """Detector communication initialization: connects every currently activated QCM."""
        try:
            labels = self.refresh_available_ports()
            self.assign_free_units(labels)
            self.sync_controllers()
        except Exception as e:
            logger.exception('STM-2 initialization failed')
            self._report_error(f'STM-2 initialization failed : {e}')
            return f'STM-2 initialization failed : {e}', False

        channels = self._active_channels()
        controller_names = list(self.controllers.keys())

        if channels and controller_names:
            dummy_dfp = []
            for channel in channels:
                _, unit = self._channel_getters[channel]
                dummy_dfp.append(
                    DataFromPlugins(name=channel,
                                    data=[np.array([0.0]) for _ in controller_names],
                                    dim='Data0D',
                                    labels=controller_names,
                                    units=unit))
            self.dte_signal_temp.emit(DataToExport('STM-2 Group Data', data=dummy_dfp))

        initialized = len(self.controllers) > 0
        info = f"{len(self.controllers)} STM-2 connected : {', '.join(self.controllers.keys())}"
        return info, initialized

    def close(self):
        """Terminate the communication protocol with every connected STM-2."""
        for ctrl in self.controllers.values():
            ctrl.close()
        self.controllers.clear()
        self._ports_in_use.clear()

    def grab_data(self, Naverage=1, **kwargs):
        """Grab every checked channel from every connected, activated STM-2.

        One DataFromPlugins is built per checked channel (frequency/thickness/thickness_rate),
        each containing one value per connected controller — so PyMoDAQ opens/updates one window
        per channel, each showing every QCM as a separate curve.

        Naverage is not used: hardware averaging is not implemented (hardware_averaging is False),
        PyMoDAQ averages the grabs itself.
        """
        channels = self._active_channels()
        controller_names = list(self.controllers.keys())

        if not channels or not controller_names:
            return

        data_list = []
        for channel in channels:
            getter_name, unit = self._channel_getters[channel]
            values = []
            for name in controller_names:
                try:
                    value = getattr(self.controllers[name], getter_name)()
                except Exception as e:
                    self._report_error(f'Error reading {name} : {e}')
                    value = np.nan
                values.append(np.array([value]))
            data_list.append(DataFromPlugins(name=channel, data=values, dim='Data0D',
                                            labels=[f'{name}' for name in controller_names],
                                            units=unit))

        self.dte_signal.emit(DataToExport('STM-2 Group Data', data=data_list))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        self.emit_status(ThreadCommand('Update_Status', ['Stopped']))
        return ''


if __name__ == '__main__':
    main(__file__)
