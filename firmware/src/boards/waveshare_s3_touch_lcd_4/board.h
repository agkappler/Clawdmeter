#pragma once

// Waveshare ESP32-S3-Touch-LCD-4 — 480x480 square RGB LCD.
// ESP32-S3-WROOM-1-N16R8 (16MB flash, 8MB octal PSRAM), ST7701 RGB565
// parallel panel (no QSPI — first non-QSPI/AMOLED S3 port), GT911
// capacitive touch, and a CH32V003F4U6 helper MCU over I2C that gates
// LCD/touch reset, drives the backlight PWM, switches the buzzer, and
// samples battery voltage — there is no PMU and no fuel-gauge chip on this
// board. A PCF85063 RTC is present but unused, same "wired but not wired
// up" posture as the 2.06 board's RTC. BLE is stock NimBLE-Arduino over the
// ESP32-S3's own radio — shared ble.cpp works unmodified, unlike the P4.
//
// Pins, panel timings, and the CH32 register map come from Waveshare's own
// official Arduino example and IO-expander library
// (github.com/waveshareteam/ESP32-S3-Touch-LCD-4).

#define BOARD_NAME           "Waveshare S3 Touch LCD 4"

// ---- Display geometry ----
#define LCD_WIDTH            480
#define LCD_HEIGHT           480

// ---- Display bus: ST7701 over 3-wire soft SPI (init commands only) + the
// ESP32-S3's native RGB565 parallel peripheral for pixel data. No LCD_RESET
// pin here — reset is gated by the CH32V003 helper (see io_expander.h),
// which board_init() must bring up before display_hal_begin() runs.
#define LCD_SPI_CS           42
#define LCD_SPI_SCK          2
#define LCD_SPI_MOSI         1

#define LCD_DE               40
#define LCD_VSYNC            39
#define LCD_HSYNC            38
#define LCD_PCLK             41
#define LCD_R0               46
#define LCD_R1               3
#define LCD_R2               8
#define LCD_R3               18
#define LCD_R4               17
#define LCD_G0               14
#define LCD_G1               13
#define LCD_G2               12
#define LCD_G3               11
#define LCD_G4               10
#define LCD_G5               9
#define LCD_B0               5
#define LCD_B1               45
#define LCD_B2               48
#define LCD_B3               47
#define LCD_B4               21

// ---- I2C bus (shared: GT911 touch, CH32V003 helper, PCF85063 RTC) ----
#define IIC_SDA              15
#define IIC_SCL              7

// ---- Touch (GT911, 16-bit register addressing). No RST/INT pins wired to
// the ESP32 — reset goes through the CH32 helper's TP_RST line instead, and
// touch_hal_read() polls the status register directly each call, same
// posture as the P4's GT911.
#define GT911_ADDR_PRIMARY   0x5D
#define GT911_ADDR_BACKUP    0x14

// ---- CH32V003F4U6 helper controller: backlight PWM, LCD/touch reset, SYS
// power enable, buzzer enable, battery ADC. See io_expander.h for the
// register protocol. ----
#define CH32_IO_ADDR         0x24

// ---- Buttons ----
#define BTN_BACK_GPIO        0     // BOOT — primary, Space (PTT). No PWR /
                                   // secondary button on this board.

// ---- Capability flags ----
#define BOARD_HAS_SECONDARY_BUTTON 0
#define BOARD_HAS_ROTATION         0   // fixed orientation, no IMU
#define BOARD_HAS_IMU              0
#define BOARD_HAS_BATTERY          1   // CH32 ADC + divider, no PMU/fuel gauge
#define BOARD_HAS_IO_EXPANDER      1
#define BOARD_HAS_SOUND            1   // buzzer gated by CH32 BEE_EN (on/off
                                       // only — no host-side tone control)
