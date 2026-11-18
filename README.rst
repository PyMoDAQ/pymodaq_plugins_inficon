pymodaq_plugins_inficon
#######################

.. image:: https://img.shields.io/pypi/v/pymodaq_plugins_inficon.svg
   :target: https://pypi.org/project/pymodaq_plugins_inficon/
   :alt: Latest Version

.. image:: https://readthedocs.org/projects/pymodaq/badge/?version=latest
   :target: https://pymodaq.readthedocs.io/en/stable/?badge=latest
   :alt: Documentation Status

.. image:: https://github.com/PyMoDAQ/pymodaq_plugins_inficon/actions/workflows/Test.yml/badge.svg
   :target: https://github.com/PyMoDAQ/pymodaq_plugins_inficon/actions/workflows/Test.yml
   :alt: Tests

PyMoDAQ plugin for the Inficon STM-2 USB thin film rate/thickness monitors (quartz crystal microbalance).


Authors
=======

* Lucas Nicolas (lucas.nicolas@onera.fr)

Contributors
============

* Benoît Pons


Instruments
===========

Below is the list of instruments included in this plugin

Viewer0D
++++++++

* **STM-2**: control of STM-2 USB Thin Film Rate/ Thickness Monitor.
* **STM-2 Multi**: control of several STM-2, with all data plotted on one graph.


Installation instructions
=========================

* PyMoDAQ 5.2 and later, Python 3.10 and later (developed and tested with Python 3.12)
* Requires the installation of the following drivers, all available in the Download section of the
  `Inficon STM-2 web page <https://www.inficon.com/en/products/thin-film-technology/thickness-monitor-stm-2-usb-thin-film-rate>`_:

  * SMDP protocol server
  * USB installer
  * STM-2 Application software

* Another USB driver may be required for the STM-2 to be detected by the computer:
  `CP210x Windows Drivers from Silicon Labs <https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers?tab=downloads>`_
* The pyserial package is also required, it is installed together with the plugin.

The STM-2 units are searched when the detector is initialized, they are detected on the serial ports of
Silicon Labs USB/UART bridges.
