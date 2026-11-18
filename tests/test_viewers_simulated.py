"""Tests of the two viewers with simulated STM-2 units: no hardware is needed."""
import numpy as np
import pytest
from qtpy import QtWidgets

from pymodaq_plugins_inficon.hardware import stm2
from pymodaq_plugins_inficon.daq_viewer_plugins.plugins_0D.daq_0Dviewer_Inficon_STM2 import DAQ_0DViewer_Inficon_STM2
from pymodaq_plugins_inficon.daq_viewer_plugins.plugins_0D.daq_0Dviewer_Inficon_STM2_Multi import \
    DAQ_0DViewer_Inficon_STM2_Multi

from test_stm2_wrapper import FakeSerial, fake_ports, fake_serial  # noqa: F401 (fake_serial is a fixture)

SERIAL_NUMBERS = {'COM3': '111', 'COM8': '222'}
VALUES = {'S': '12.5', 'T': '1.5', 'U': '5999000.0'}


@pytest.fixture(scope='module')
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def units(fake_serial, monkeypatch, qapp):
    """Two simulated units on COM3 and COM8, and an other device of the same USB/UART bridge family."""
    monkeypatch.setattr(stm2.serial.tools.list_ports, 'comports',
                        fake_ports(('COM3', 0x10C4, 'Silicon Labs'), ('COM8', 0x10C4, 'Silicon Labs')))
    FakeSerial.replies = {'@': 'STM-2 v1', '@A': lambda port: SERIAL_NUMBERS[port], '@B': 'build', 'p': '1234',
                          'a': '@', 'M': '@', 'q?': 'film', 'E?': '2.70', 'F?': '1.000', 'r?': '5', 'B': '',
                          'E=2.5': '', **VALUES}
    return FakeSerial


def sent_commands():
    """Commands sent to all the simulated ports, as strings."""
    return [(w[3:-3] if w[2] == 0x80 else w[2:-3]).decode()
            for inst in FakeSerial.instances for w in inst.written]


def test_viewers_can_be_created_without_hardware(monkeypatch, qapp):
    monkeypatch.setattr(stm2.serial.tools.list_ports, 'comports', fake_ports())
    single = DAQ_0DViewer_Inficon_STM2()
    info, initialized = single.ini_detector()
    assert not initialized and 'not found' in info
    multi = DAQ_0DViewer_Inficon_STM2_Multi()
    assert not multi.ini_detector()[1]


def test_single_viewer(units):
    viewer = DAQ_0DViewer_Inficon_STM2()
    emitted = []
    viewer.dte_signal.connect(emitted.append)
    info, initialized = viewer.ini_detector()
    assert initialized
    assert viewer.settings.child('film_density').value() == 2.7
    assert viewer.settings.child('samples_number').value() == 5
    assert 'B' not in sent_commands()  # thickness not zeroed on connection

    viewer.grab_data()
    dte = emitted[-1]
    assert [d.units for d in dte.data] == ['Hz', 'Å', 'Å/s']
    assert float(dte.data[1].data[0][0]) == 12.5

    param = viewer.settings.child('film_density')
    param.setValue(2.5)
    viewer.commit_settings(param)  # sent to the unit
    assert 'E=2.5' in sent_commands()
    viewer.close()
    assert viewer.controller is None
    assert all(not inst.is_open for inst in FakeSerial.instances)


def test_single_viewer_zero_on_connect_is_opt_in(units):
    viewer = DAQ_0DViewer_Inficon_STM2()
    viewer.settings.child('zero_on_connect').setValue(True)
    assert viewer.ini_detector()[1]
    assert 'B' in sent_commands()


def test_single_viewer_slave_uses_given_controller(units, monkeypatch):
    monkeypatch.setattr(DAQ_0DViewer_Inficon_STM2, 'is_master', property(lambda self: False))
    viewer = DAQ_0DViewer_Inficon_STM2()
    controller = stm2.InficonSTM2('COM8')
    assert viewer.ini_detector(controller)[1]
    assert viewer.controller is controller


def test_multi_viewer(units):
    viewer = DAQ_0DViewer_Inficon_STM2_Multi()
    emitted = []
    viewer.dte_signal.connect(emitted.append)
    info, initialized = viewer.ini_detector()
    assert initialized
    assert set(viewer.controllers) == {'qcm_1', 'qcm_2'}  # the two units were given to the first two QCM
    assert {c.port for c in viewer.controllers.values()} == {'COM3', 'COM8'}
    assert 'B' not in sent_commands()  # thickness not zeroed on connection

    viewer.grab_data()
    dte = emitted[-1]
    assert [d.name for d in dte.data] == ['frequency', 'thickness', 'thickness_rate']
    assert [d.units for d in dte.data] == ['Hz', 'Å', 'Å/s']
    assert all(len(d.data) == 2 for d in dte.data)
    assert np.allclose([d.data[0][0] for d in dte.data], [5999000.0, 12.5, 1.5])

    viewer.close()
    assert not viewer.controllers
    assert all(not inst.is_open for inst in FakeSerial.instances)
