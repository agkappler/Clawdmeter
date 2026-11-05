#include "../../hal/power_hal.h"
#include "board.h"
#include "fuel_gauge.h"
#include <Arduino.h>

// No PMU and no PWR button on this board (see board.h) — battery % and
// charge state come from the BQ27220 fuel gauge instead. The gauge has no
// charger-present signal, so USB power is inferred from the battery not
// discharging: a full battery on USB reads ~0 mA, on battery it reads
// clearly negative. A missing gauge reads 0 mA, i.e. powered, which is right
// for a battery-less unit that can only run from USB.

#define BATTERY_POLL_MS        2000
#define CHARGING_MIN_MA        10
#define DISCHARGING_MAX_MA     (-10)

static int      cached_pct      = -1;
static bool     cached_charging = false;
static bool     cached_vbus     = false;
static uint32_t last_battery_ms = 0;

static void read_gauge(void) {
    cached_pct = fuel_gauge_read_pct();
    int ma = fuel_gauge_read_current_ma();
    cached_charging = ma > CHARGING_MIN_MA;
    cached_vbus     = ma > DISCHARGING_MAX_MA;
}

void power_hal_init(void) {
    fuel_gauge_init();
    read_gauge();
}

void power_hal_tick(void) {
    uint32_t now = millis();
    if (now - last_battery_ms >= BATTERY_POLL_MS) {
        last_battery_ms = now;
        read_gauge();
    }
}

int  power_hal_battery_pct(void) { return cached_pct; }
bool power_hal_is_charging(void) { return cached_charging; }
bool power_hal_is_vbus_in(void)  { return cached_vbus; }

// No PWR button on this board's stock hardware — splash-cycling,
// brightness-cycling, and the hold-to-pair gesture are unavailable here.
bool power_hal_pwr_pressed(void)      { return false; }
bool power_hal_pwr_long_pressed(void) { return false; }
bool power_hal_pwr_released(void)     { return false; }
