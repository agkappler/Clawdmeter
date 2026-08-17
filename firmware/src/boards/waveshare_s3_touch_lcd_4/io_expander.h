#pragma once
#include <stdint.h>

// CH32V003F4U6 helper controller — a small RISC-V MCU running Waveshare's
// own firmware, not a passive register-mapped IO expander chip. Exposed
// over I2C as a handful of registers: it gates LCD_RST/TP_RST/SYS_EN,
// drives the backlight via PWM, switches the buzzer on/off, and samples
// battery voltage on an onboard ADC. Board-private to this port; not
// exposed in hal/.
//
// Protocol reverse-derived from Waveshare's own WS_CH32_IO Arduino library
// (waveshareteam/ESP32-S3-Touch-LCD-4, examples/arduino/libraries/WS_CH32_IO).
//
// Must be initialized BEFORE the display or touch — both stay in reset
// until ch32_init() releases LCD_RST/TP_RST.

bool ch32_init(void);
bool ch32_set_backlight(uint8_t duty);      // 0..255 PWM duty
bool ch32_set_buzzer(bool on);              // on/off only — the CH32
                                             // firmware drives its own fixed
                                             // tone, no host-side pitch/duration
bool ch32_read_battery_raw(uint16_t* raw);  // 10-bit ADC sample (0..1023)
