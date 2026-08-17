#include "../../hal/sound_hal.h"
#include "io_expander.h"
#include <Arduino.h>

// The CH32V003 helper only exposes buzzer on/off (BEE_EN) — no host-side
// pitch/duration control like the LEDC-PWM boards' note sequencer, so this
// plays a single fixed-length beep instead of a melody.

#define BEEP_MS 150

static bool     playing = false;
static uint32_t off_at_ms = 0;

void sound_hal_init(void) {}

void sound_hal_tick(void) {
    if (playing && millis() >= off_at_ms) {
        ch32_set_buzzer(false);
        playing = false;
    }
}

void sound_hal_play_reset(void) {
    ch32_set_buzzer(true);
    off_at_ms = millis() + BEEP_MS;
    playing = true;
}
