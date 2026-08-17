#include "io_expander.h"
#include "board.h"
#include <Arduino.h>
#include <Wire.h>

// Register map + reset timing straight from Waveshare's WS_CH32_IO library.
#define REG_DIRECTION 0x02
#define REG_OUTPUT    0x03
#define REG_ADC       0x06

#define PIN_TP_RST   (1 << 1)
#define PIN_LCD_RST  (1 << 3)
#define PIN_SYS_EN   (1 << 5)
#define PIN_BEE_EN   (1 << 6)

#define DIR_DEFAULT    0xFF
#define OUT_RESET      0x00
#define OUT_DISPLAY_ON (PIN_SYS_EN | PIN_LCD_RST | PIN_TP_RST)

static uint8_t output_state = 0;

static bool write_reg(uint8_t reg, uint8_t val) {
    for (uint8_t attempt = 0; attempt < 5; attempt++) {
        Wire.beginTransmission(CH32_IO_ADDR);
        Wire.write(reg);
        Wire.write(val);
        if (Wire.endTransmission() == 0) return true;
        delay(10 + attempt * 10);
    }
    return false;
}

static bool read_regs(uint8_t reg, uint8_t* buf, uint8_t len) {
    for (uint8_t attempt = 0; attempt < 5; attempt++) {
        Wire.beginTransmission(CH32_IO_ADDR);
        Wire.write(reg);
        if (Wire.endTransmission(false) == 0 &&
            Wire.requestFrom((int)CH32_IO_ADDR, (int)len) == len) {
            for (uint8_t i = 0; i < len; i++) buf[i] = Wire.read();
            return true;
        }
        delay(10 + attempt * 10);
    }
    return false;
}

bool ch32_init(void) {
    // Same probe -> hold-in-reset -> 200ms -> release -> 200ms sequence as
    // Waveshare's own initDisplayPower().
    for (int attempt = 0; attempt < 3; attempt++) {
        Wire.beginTransmission(CH32_IO_ADDR);
        if (Wire.endTransmission() != 0) { delay(20); continue; }

        if (!write_reg(REG_DIRECTION, DIR_DEFAULT)) { delay(20); continue; }
        if (!write_reg(REG_OUTPUT, OUT_RESET))       { delay(20); continue; }
        delay(200);

        output_state = OUT_DISPLAY_ON;
        if (!write_reg(REG_DIRECTION, DIR_DEFAULT)) { delay(20); continue; }
        if (!write_reg(REG_OUTPUT, output_state))    { delay(20); continue; }
        delay(200);

        Serial.println("CH32V003 helper initialized");
        return true;
    }
    Serial.println("CH32V003 helper init failed");
    return false;
}

bool ch32_set_backlight(uint8_t duty) {
    return write_reg(0x05 /* REG_PWM */, duty);
}

bool ch32_set_buzzer(bool on) {
    if (on) output_state |= PIN_BEE_EN;
    else    output_state &= ~PIN_BEE_EN;
    return write_reg(REG_OUTPUT, output_state);
}

bool ch32_read_battery_raw(uint16_t* raw) {
    uint8_t data[2];
    if (!read_regs(REG_ADC, data, sizeof(data))) return false;
    *raw = (uint16_t)data[0] | ((uint16_t)data[1] << 8);  // little-endian
    return true;
}
