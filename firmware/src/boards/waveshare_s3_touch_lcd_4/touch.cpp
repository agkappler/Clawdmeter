#include "../../hal/touch_hal.h"
#include "board.h"
#include <Arduino.h>
#include <Wire.h>

// Minimal inline GT911 reader — same register layout already verified on
// real hardware for the P4 port (boards/waveshare_p4_touch_lcd_5/touch.cpp);
// see that file's header comment for the two-session debugging story behind
// these exact offsets. This board's GT911 also has no RST/INT pins wired to
// the ESP32 (reset goes through the CH32 helper's TP_RST line instead), so
// touch_hal_read() polls the status register directly each call.
//
//   reg 0x814E: bit7 = data-ready, bits[3:0] = touch point count (0-5)
//   reg 0x814F: point 1 record (8 bytes) — [track_id, xL, xH, yL, yH, sL, sH, rsvd]
//   Little-endian coordinate pairs, record starting at 0x814F.
//
// The panel is driven at a fixed rotation=1 in display.cpp (USB/power port
// mounted on the bottom edge), so raw GT911 coordinates are transformed here
// to match — same case-1 mapping as Waveshare's own example's touch handler
// (touchX = rawY, touchY = height - rawX), just applied unconditionally
// since this board's rotation never changes at runtime.

static uint8_t gt911_addr = 0;

static bool gt911_write16(uint16_t reg, uint8_t val) {
    Wire.beginTransmission(gt911_addr);
    Wire.write((uint8_t)(reg >> 8));
    Wire.write((uint8_t)(reg & 0xFF));
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

static bool gt911_read(uint16_t reg, uint8_t* buf, uint8_t len) {
    Wire.beginTransmission(gt911_addr);
    Wire.write((uint8_t)(reg >> 8));
    Wire.write((uint8_t)(reg & 0xFF));
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(gt911_addr, len) != len) return false;
    for (uint8_t i = 0; i < len; i++) buf[i] = Wire.read();
    return true;
}

static bool gt911_probe(uint8_t addr) {
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

void touch_hal_init(void) {
    if (gt911_probe(GT911_ADDR_PRIMARY)) {
        gt911_addr = GT911_ADDR_PRIMARY;
    } else if (gt911_probe(GT911_ADDR_BACKUP)) {
        gt911_addr = GT911_ADDR_BACKUP;
    } else {
        Serial.println("Touch GT911 not found on either address");
        return;
    }
    Serial.printf("Touch GT911 found at 0x%02X\n", gt911_addr);
}

// Returns false if no fresh sample was available (caller should not treat
// that as "not pressed" — see touch_hal_read()).
static bool gt911_read_point(uint16_t* out_x, uint16_t* out_y) {
    uint8_t status = 0;
    if (!gt911_read(0x814E, &status, 1)) return false;
    if (!(status & 0x80)) return false;  // no fresh data

    uint8_t points = status & 0x0F;
    if (points == 0 || points > 5) {
        gt911_write16(0x814E, 0x00);  // clear and bail
        return false;
    }

    uint8_t rec[8];
    bool ok = gt911_read(0x814F, rec, sizeof(rec));
    gt911_write16(0x814E, 0x00);  // tell the controller we've consumed this sample
    if (!ok) return false;

    // rec[0] = track id, rec[1..2] = X (LE), rec[3..4] = Y (LE)
    uint16_t raw_x = (uint16_t)rec[1] | ((uint16_t)rec[2] << 8);
    uint16_t raw_y = (uint16_t)rec[3] | ((uint16_t)rec[4] << 8);

    // rotation=1 mapping (see file header): touchX = rawY, touchY = height - rawX.
    *out_x = raw_y;
    *out_y = (raw_x < LCD_HEIGHT) ? (LCD_HEIGHT - raw_x) : 0;
    return true;
}

void touch_hal_read(uint16_t* x, uint16_t* y, bool* pressed) {
    *pressed = false;
    if (!gt911_addr) return;

    uint16_t rx, ry;
    if (!gt911_read_point(&rx, &ry)) return;

    *x = rx;
    *y = ry;
    *pressed = true;
}
