// (C) 2015 Kyoto University Mechatronics Laboratory
// Released under the GNU General Public License, version 3
#include "mbed.h"
Serial rpi(USBTX, USBRX); // USB port acts as a serial connection with rpi.
// A bitfield representing the motor packet received from the rpi.
//
// The first two bits of the packet represent the motor ID, between 0 and 3.
// The third bit is the sign, with a value of 1 when negative and 0 when
// positive. The last five bits represent the speed, with a value between 0
// and 31. [0:31] corresponds to a [0:1] requested speed.
//
// If the sign is 1 and the speed is zero, the motor ID of the packet is
// instead used to request updated data from up to four ADC channels.
struct MotorPacketBits {
                        unsigned int motor_id : 2;
                        unsigned int negative : 1;
                        unsigned int speed : 5;
                       };

union MotorPacket {
                   struct MotorPacketBits b;
                   unsigned char as_byte;
                  };
     
                  
// Class representing a motor driver.
//
// Connect the PWM and DIR pins to the mbed. The motor driver's fault signals
// should go to the Raspberry Pi. Ground can be connected to
// either.
//
// Datasheet: https://www.pololu.com/product/755
//
// Sample usage:
// Motor motor(p21, p11);
// motor.drive(0.5) // Runs motor forward at 50% speed.
// motor.drive(-0.5) // Runs motor backwards at 50% speed.
class Motor {
    public:
        // Initialize the motor.
        //
        // Args:
        // pin_pwm: The motor driver's PWM pin. In order to have PWM output,
        // the pin should be between 21 and 26.
        // pin_dir: The motor driver's DIR pin. HI is forward, LO is reverse.
        Motor(PinName pin_pwm, PinName pin_dir) : pwm(pin_pwm), dir(pin_dir) {
            pwm = dir = 0; // Set all outputs to low.
            pwm.period_us(40); // Set PWM output frequency to 25 kHz.
        }
        
        // Drive the motor at the given speed.
        //
        // Args:
        // speed: A value between -1 and 1, representing the speed of the motor.
        void drive(float speed) {
            dir = speed < 0 ? 0 : 1;
            pwm = abs(speed);
        }
        
    private:
        // Variables:
        // pwm: PwmOut for the motor driver's PWM pin.
        // dir: DigitalOut for the motor driver's direction pin.
        PwmOut pwm;
        DigitalOut dir;
};


int main() {
    // The four motors are in an array. The raspberry pi expects this order;
    // do not change it without changing the code for the rpi as well.
    Motor motors[4] = { Motor(p21, p11),   // Left wheels
                        Motor(p22, p12),   // Right wheels
                        Motor(p23, p13),   // Left flipper
                        Motor(p24, p14) }; // Right flipper
    
    // Set up ADC ports. If you add ADC devices, please add them in order
    // from the lowest pin to the highest.
    AnalogIn pots[6] = {p15, p16, p17, p18,  // Unused 
                        p19,                 // Left flipper position
                        p20};                // Right flipper position
    
    int n_adc = 2; // Number of ADC Channels in use. Max is 6.
    uint16_t adc_results[n_adc];
    for (int i = 0; i < n_adc; i++) {
        adc_results[i] = 0; // Zero the results.
    }
    
    union MotorPacket packet;
    int sign;
    
    while(1) {
        // Drive the motor
        if(rpi.readable()) {
            packet.as_byte = rpi.getc(); // Get packet from rpi.
        }

        // If speed is 0 but negative is true, you can consider these as special
        // requests, and you may do whatever you want. Since there is a maximum
        // of 4 motor IDs, you can use a switch statement.
        // 
        // It is best if you write a function and simply call it from here.
        //
        // Uncomment this code to use it.
        if(packet.b.negative and !packet.b.speed) {
        /*
            switch(packet.b.motor_id) {
                case 0:
                    // Code
                    break;
                case 1:
                    // Code
                    break;
                case 2:
                    // Code
                    break;
                case 3:
                    // Code
                    break;
            }
        */
        }
        else { // Drive motor.
            sign = packet.b.negative ? -1 : 1;
            motors[packet.b.motor_id].drive(sign * packet.b.speed / 31.0);
        }

        // Update extra ADC results.
        for(int i = 0; i < n_adc - 2; i++)
        {
            adc_results[i] = pots[i].read_u16();
        }
        
        adc_results[n_adc - 2] = pots[4].read_u16();  // Left flipper position
        adc_results[n_adc - 1] = pots[5].read_u16();  // Right flipper position

        // Send data to Rpi.
        for(int i = 0; i < n_adc; i++) {
            rpi.printf("0x%X ", adc_results[i]);
        }

        rpi.printf("\n");
    }
}
