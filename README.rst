pymodaq_plugins_inficon
########################

.. the following must be adapted to your developed package, links to pypi, github  description...

.. image:: https://img.shields.io/pypi/v/pymodaq_plugins_template.svg
   :target: https://pypi.org/project/pymodaq_plugins_template/
   :alt: Latest Version

.. image:: https://readthedocs.org/projects/pymodaq/badge/?version=latest
   :target: https://pymodaq.readthedocs.io/en/stable/?badge=latest
   :alt: Documentation Status

.. image:: https://github.com/PyMoDAQ/pymodaq_plugins_template/workflows/Upload%20Python%20Package/badge.svg
   :target: https://github.com/PyMoDAQ/pymodaq_plugins_template
   :alt: Publication Status

.. image:: https://github.com/PyMoDAQ/pymodaq_plugins_template/actions/workflows/Test.yml/badge.svg
    :target: https://github.com/PyMoDAQ/pymodaq_plugins_template/actions/workflows/Test.yml


Use this template to create a repository on your account and start the development of your own PyMoDAQ plugin!


Authors
=======

* Lucas Nicolas  (lucas.nicolas@onera.fr)

.. if needed use this field

    Contributors
    ============

    * Benoît Pons


.. if needed use this field

  Depending on the plugin type, delete/complete the fields below


Instruments
===========

Below is the list of instruments included in this plugin

Viewer0D
++++++++

* **STM-2**: control of STM-2 USB Thin Film Rate/ Thickness Monitor.
* **STM-2 Multi**: control of several STM-2, with all data plotted on one graph.



Installation instructions
=========================

* PyMoDAQ’s 5.0.x and later
* Requires installation of the following drivers:
        SMDP protocol server
        USB installer
        STM-2 Application software
    They are all available in the Download section of the Inficon STM-2 web page:
        https://www.inficon.com/en/products/thin-film-technology/thickness-monitor-stm-2-usb-thin-film-rate
    Another USB driver may be required for the STM-2 to be detected by the computer:
        CP210x Windows Drivers from Silicon Labs: https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers?tab=downloads
    pyserial package is also required.
