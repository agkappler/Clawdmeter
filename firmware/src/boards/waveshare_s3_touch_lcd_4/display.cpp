#include "../../hal/display_hal.h"
#include "board.h"
#include "io_expander.h"
#include <Arduino.h>
#include <Arduino_GFX_Library.h>

// ST7701 RGB565 parallel panel — first non-QSPI/AMOLED S3 port. There is no
// dedicated Arduino_GFX ST7701 class; Arduino_RGB_Display takes a raw vendor
// init-command table instead (st7701_type1_init_operations, built into the
// library's Arduino_RGB_Display.h) driven over a 3-wire soft-SPI init bus,
// with pixel data pushed over the ESP32-S3's native parallel RGB peripheral
// (Arduino_ESP32RGBPanel). Pins, sync timings, and the rotation value are
// Waveshare's own official Arduino example
// (waveshareteam/ESP32-S3-Touch-LCD-4/examples/arduino/09_LVGL_Widgets)
// verbatim.
//
// No LCD_RESET pin passed to the GFX driver (GFX_NOT_DEFINED) — reset is
// gated by the CH32V003 helper controller instead (see io_expander.h);
// board_init() runs ch32_init() before this HAL is touched.

static Arduino_DataBus*       bus = nullptr;
static Arduino_ESP32RGBPanel* rgbpanel = nullptr;
static Arduino_RGB_Display*   gfx = nullptr;

void display_hal_init(void) {
    bus = new Arduino_SWSPI(
        GFX_NOT_DEFINED /* DC */, LCD_SPI_CS,
        LCD_SPI_SCK, LCD_SPI_MOSI, GFX_NOT_DEFINED /* MISO */);

    rgbpanel = new Arduino_ESP32RGBPanel(
        LCD_DE, LCD_VSYNC, LCD_HSYNC, LCD_PCLK,
        LCD_R0, LCD_R1, LCD_R2, LCD_R3, LCD_R4,
        LCD_G0, LCD_G1, LCD_G2, LCD_G3, LCD_G4, LCD_G5,
        LCD_B0, LCD_B1, LCD_B2, LCD_B3, LCD_B4,
        1 /* hsync_polarity */, 10 /* hsync_front_porch */, 8 /* hsync_pulse_width */, 50 /* hsync_back_porch */,
        1 /* vsync_polarity */, 10 /* vsync_front_porch */, 8 /* vsync_pulse_width */, 20 /* vsync_back_porch */,
        0 /* pclk_active_neg */, GFX_NOT_DEFINED /* prefer_speed */, false /* useBigEndian */,
        0 /* de_idle_high */, 0 /* pclk_idle_high */,
        // Bounce buffer: a small internal-SRAM staging region the RGB DMA engine
        // reads through instead of PSRAM directly. Waveshare's own example leaves
        // this at the disabled default (0), fine for its sparse redraws, but our
        // animated LVGL UI writes into the live single PSRAM framebuffer often
        // enough that the panel's continuous DMA scan-out visibly tears/flickers
        // without it — 10 rows is the starting point ESP-IDF's own RGB panel
        // examples use.
        LCD_WIDTH * 10 /* bounce_buffer_size_px */);

    // rotation=2 matches Waveshare's own example — the panel's native mount
    // reads upside-down relative to how the board sits right-side up.
    // Fixed at build time (no runtime rotation on this board); touch.cpp
    // applies the matching coordinate flip.
    gfx = new Arduino_RGB_Display(
        LCD_WIDTH, LCD_HEIGHT, rgbpanel, 2 /* rotation */, true /* auto_flush */,
        bus, GFX_NOT_DEFINED /* RST — via CH32 helper */,
        st7701_type1_init_operations, sizeof(st7701_type1_init_operations));
}

void display_hal_begin(void) {
    if (!gfx) return;
    gfx->begin();
    gfx->fillScreen(0x0000);
}

void display_hal_set_brightness(uint8_t level) {
    // Backlight is a CH32-driven PWM channel over I2C, not a local GPIO —
    // unlike the LEDC-PWM boards (e.g. LCD-1.85B) or OLED command-based
    // brightness (the AMOLED boards).
    ch32_set_backlight(level);
}

void display_hal_fill_screen(uint16_t color) {
    if (gfx) gfx->fillScreen(color);
}

void display_hal_draw_bitmap(int32_t x, int32_t y, int32_t w, int32_t h,
                             const uint16_t* pixels) {
    if (gfx) gfx->draw16bitRGBBitmap(x, y, (uint16_t*)pixels, w, h);
}

void display_hal_tick(void) {
    // No rotation handling needed — fixed orientation, no IMU.
}

void display_hal_round_area(int32_t* x1, int32_t* y1, int32_t* x2, int32_t* y2) {
    // No even-alignment requirement documented for this RGB panel (that's a
    // CO5300-specific QSPI quirk); pass through unchanged.
    (void)x1; (void)y1; (void)x2; (void)y2;
}
