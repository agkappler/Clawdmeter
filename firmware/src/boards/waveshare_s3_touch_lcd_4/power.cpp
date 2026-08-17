#include "../../hal/power_hal.h"
#include "io_expander.h"
#include <Arduino.h>

// No PMU and no fuel-gauge chip on this board — battery voltage comes from
// the CH32V003 helper's own ADC (10-bit, 3.3V ref, 3.0x resistive divider —
// see io_expander.h). Charging state and VBUS presence aren't exposed by
// the CH32 protocol at all, so they're honestly reported as unknown rather
// than guessed. No PWR button either (BOOT/GPIO0 is the board's only
// physical input), so splash-cycling and hold-to-pair are unavailable, same
// posture as the P4 and LCD-1.85B ports.

#define BATT_ADC_REF   3.3f
#define BATT_ADC_MAX   1023.0f
#define BATT_DIVIDER   3.0f
// Typical single-cell LiPo range — there's no fuel-gauge curve to defer to
// on this board, so this is a plain linear estimate.
#define BATT_V_EMPTY   3.3f
#define BATT_V_FULL    4.2f

#define BATT_SAMPLE_INTERVAL_MS 2000  // ADC read is an I2C round trip; no need to poll every loop

static int      batt_pct = -1;
static uint32_t last_sample_ms = 0;

void power_hal_init(void) {}

void power_hal_tick(void) {
    uint32_t now = millis();
    if (last_sample_ms != 0 && now - last_sample_ms < BATT_SAMPLE_INTERVAL_MS) return;
    last_sample_ms = now;

    uint16_t raw;
    if (!ch32_read_battery_raw(&raw)) return;
    if (raw > 1023) raw = 1023;

    float voltage = (raw * BATT_ADC_REF / BATT_ADC_MAX) * BATT_DIVIDER;
    float pct = (voltage - BATT_V_EMPTY) / (BATT_V_FULL - BATT_V_EMPTY) * 100.0f;
    if (pct < 0.0f) pct = 0.0f;
    if (pct > 100.0f) pct = 100.0f;
    batt_pct = (int)(pct + 0.5f);
}

int  power_hal_battery_pct(void) { return batt_pct; }
bool power_hal_is_charging(void) { return false; }  // not exposed by the CH32 protocol
bool power_hal_is_vbus_in(void)  { return false; }  // not exposed by the CH32 protocol
bool power_hal_pwr_pressed(void) { return false; }
bool power_hal_pwr_long_pressed(void) { return false; }
bool power_hal_pwr_released(void) { return false; }
