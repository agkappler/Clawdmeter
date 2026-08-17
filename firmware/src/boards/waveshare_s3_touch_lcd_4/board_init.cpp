#include "board.h"
#include "io_expander.h"
#include <Arduino.h>
#include <Wire.h>

// Bus-recovery pulse before Wire.begin(): if a previous crash/reset left a
// device mid-transaction holding SDA low, clock up to 9 pulses to free it.
// Same recovery Waveshare's own WS_CH32_IO::begin() and ESP-IDF example run
// before every boot — cheap insurance against the CH32 helper (and with it,
// the LCD/touch reset lines) being unreachable after a bad reset.
static void i2c_bus_recover(void) {
    pinMode(IIC_SDA, INPUT_PULLUP);
    pinMode(IIC_SCL, OUTPUT);
    digitalWrite(IIC_SCL, HIGH);
    delayMicroseconds(10);

    for (int i = 0; i < 9 && digitalRead(IIC_SDA) == LOW; i++) {
        digitalWrite(IIC_SCL, LOW);
        delayMicroseconds(10);
        digitalWrite(IIC_SCL, HIGH);
        delayMicroseconds(10);
    }

    pinMode(IIC_SDA, OUTPUT);
    digitalWrite(IIC_SDA, LOW);
    delayMicroseconds(10);
    digitalWrite(IIC_SCL, HIGH);
    delayMicroseconds(10);
    digitalWrite(IIC_SDA, HIGH);
    delayMicroseconds(10);

    pinMode(IIC_SDA, INPUT_PULLUP);
    pinMode(IIC_SCL, INPUT_PULLUP);
    delay(2);
}

// The CH32V003 helper gates LCD_RST and TP_RST — it must be up and have
// released both before display_hal_init()/touch_hal_init() run.
extern "C" void board_init(void) {
    i2c_bus_recover();
    Wire.begin(IIC_SDA, IIC_SCL);
    Wire.setClock(400000);
    ch32_init();
}
