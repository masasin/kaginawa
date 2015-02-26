# (C) 2015  Kyoto University Mechatronics Laboratory
# Released under the GNU General Public License, version 3
import ctypes
import logging

from RPi import GPIO as gpio

from ..common.exceptions import DriverError


class MotorPacketBits(ctypes.BigEndianStructure):
    """The bits for the packet sent to the motors."""
    _fields_ = [("motor_id", ctypes.c_uint8, 2),
                ("negative", ctypes.c_uint8, 1),
                ("speed", ctypes.c_uint8, 5)]


class MotorPacket(ctypes.Union):
    """The packet sent to the motors"""
    _fields_ = [("b", MotorPacketBits),
                ("as_byte", ctypes.c_uint8)]

    _anonymous_ = ("b")


class Motor(object):
    """Class for encapsulating motors. Up to 4 motors can be registered.

    Datasheet: https://www.pololu.com/product/755

    Attributes:
        name: The name of the motor.
        motor_id: The motor ID. It is generated automatically.
        pin_fault_1: The GPIO pin for the motor Fault line, F1.
        pin_fault_2: The GPIO pin for the motor Fault line, F2.
        has_serial: A serial port is open, and hardware PWM is available.
        has_pwm: Software PWM is available.
        connection: The serial port to be used for communication.
        pin_pwm: The GPIO pin for motor PWM line.
        pin_dir: The GPIO pin for motor DIR line.
        start_input: The input at which the motor starts responding.
        max_speed: The maximum speed to use with the motor.
        motors: A class variable containing all registered motors.
    """
    gpio.setmode(gpio.BOARD)
    motors = []

    def __init__(self, name, fault_1, fault_2, start_input=0, max_speed=1):
        """Inits and registers the motor.

        Args:
            name: The name of the motor.
            fault_1: GPIO pin for the motor Fault line, F1.
            fault_2: GPIO pin for the motor Fault line, F2.
            start_input: (optional) The input at which the motor starts
                responding. Can range between 0 and 1. Default is 0.
            max_speed: (optional) The maximum speed to use with the motor.
                Can range between 0 and 1. Default is 1.

        Raises:
            IndexError: All four motors have been registered.
            ValueError: Bad inputs.
        """
        if Motor.motors[-1].motor_id == 3:
            raise IndexError("4 motors have already been registered.")
        if not 0 <= start_input <= 1:
            raise ValueError("start_input can only range between 0 and 1.")
        if not 0 <= max_speed <= 1:
            raise ValueError("max_speed can only range between 0 and 1.")

        self.logger = logging.getLogger(name)
        self.logger.debug("Initializing motor")
        self.motor_id = len(Motor.motors)
        self.name = name
        self.pin_fault_1 = fault_1
        self.pin_fault_2 = fault_2
        self.start_input = start_input
        self.max_speed = max_speed
        self.has_serial = False
        self.has_pwm = False

        self.logger.debug("Setting up fault interrupt")
        gpio.setup(fault_1, gpio.IN, pull_up_down=gpio.PUD_DOWN)  # Pull up
        gpio.setup(fault_2, gpio.IN, pull_up_down=gpio.PUD_DOWN)  # Pull up
        gpio.add_event_detect(fault_1, gpio.RISING, callback=self._catch_fault)
        gpio.add_event_detect(fault_2, gpio.RISING, callback=self._catch_fault)

        self.logger.debug("Registering motor")
        Motor.motors.append(self)
        self.logger.info("Motor initialized")

    def enable_pwm(self, pwm, direction, frequency=28000):
        """Allow soft pwm to control the motor.

        The motor in this case needs to be attached directly to the rpi.

        Args:
            pwm: The GPIO pin for the motor driver PWM line.
            direction: The GPIO pin for the motor driver DIR line.
            frequency: (optional) The frequency of the software pwm. Default is
                28000.
        """
        self.pin_pwm = pwm
        self.pin_dir = direction

        self.logger.debug("Setting up GPIO pins")
        gpio.setup(self.pin_pwm, gpio.OUT)
        gpio.setup(self.pin_dir, gpio.OUT)

        self.logger.debug("Starting PWM drivers")
        gpio.output(self.pin_dir, gpio.LOW)
        self._pwm = gpio.PWM(self.pin_pwm, frequency)
        self._pwm.start(0)

        self.has_pwm = True

    def enable_serial(self, connection):
        """Allow the use of a USB serial connection.

        This is needed if you want to use hardware PWM with an external
        microcontroller, such as the mbed.

        Args:
            connection: The Serial object used to communicate.
        """
        self.connection = connection
        self.has_serial = True

    def _catch_fault(self, channel):
        """Threaded callback for fault detection."""
        self.logger.warning("Fault detected")

    def _scale_speed(self, speed):
        """Get the scaled speed according to input parameters.

        Args:
            speed: A value from -1 to 1 indicating the requested speed.

        Returns:
            The scaled speed
        """
        # Map [start_input:1] to [0:1]
        if speed > 0:
            speed = (speed * (1 - self.start_input)) + self.start_input
        elif speed < 0:
            speed = (speed * (1 - self.start_input)) - self.start_input

        # Map [0:1] to [0:max_speed]
        speed *= self.max_speed
        speed = round(speed, 4)
        return speed

    def _transmit(self, speed):
        """Send a byte through a serial connection.

        When connected to the mbed, motor control information is encoded as a
        single byte, with the first two bits encoding the motor's ID, and the
        next bit encoding the sign. The last five bits encode the absolute
        value of the speed to a number between 0 and 31.

        This allows only the relevant information to be transmitted, and also
        lets the mbed perform asynchronously.

        Args:
            speed: A value from -1 to 1 indicating the requested speed.
        """
        packet = MotorPacket()
        packet.motor_id = self.motor_id
        packet.negative = 1 if speed < 0 else 0
        packet.speed = int(abs(self._scale_speed(speed)) * 31)

        self.connection.write(bytes([packet.as_byte]))

    def _pwm_drive(self, speed):
        """Drive the motor using the PWM pin.

        DIR is set depending on the speed requested.

        Args:
            speed: A value from -1 to 1 indicating the requested speed of the
                motor. The speed is changed by changing the PWM duty cycle.
        """
        speed = self._scale_speed(speed)

        gpio.output(self.pin_dir, gpio.LOW if speed < 0 else gpio.HIGH)
        self._pwm.ChangeDutyCycle(abs(speed) * 100)

    def drive(self, speed):
        """Drive the motor at a given speed.

        The priority goes to the mbed if serial is enabled. Software PWM is
        used as a backup, if it is enabled.

        Args:
            speed: A value from -1 to 1 indicating the requested speed.

        Raises:
            DriverError: Neither serial nor PWM are enabled.
        """
        if self.has_serial:
            self._transmit(speed)
        elif self.has_pwm:
            self._pwm_drive(speed)
        else:
            self.logger.error("Cannot drive motor! No serial or PWM enabled.")
            raise DriverError("{} has no drivers enabled.".format(self.name))

    def shutdown(self):
        """Shut down and deregister the motor."""
        self.logger.debug("Shutting down motor")
        self.logger.debug("Stopping motor")
        self.drive(0)

        self.logger.debug("Deregistering motor")
        Motor.motors.remove(self)
        self.logger.info("Motor shut down")

    @classmethod
    def shutdown_all(self):
        """A class method to shut down and deregister all motors."""
        logging.info("Shutting down all motors.")
        for motor in Motor.motors:
            motor.shutdown()
        gpio.cleanup()
        logging.info("All motors shut down")

    def __repr__(self):
        return "{} (ID# {})".format(self.name, self.motor_id)

    def __str__(self):
        return self.name
