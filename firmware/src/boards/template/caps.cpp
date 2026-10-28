#include "../../hal/board_caps.h"
#include "board.h"

static const BoardCaps caps = {
    .name = BOARD_NAME,
    .width = LCD_WIDTH,
    .height = LCD_HEIGHT,
    .button_count = (uint8_t)(1 + BOARD_HAS_SECONDARY_BUTTON),
    .has_rotation = (bool)BOARD_HAS_ROTATION,
    .has_battery  = (bool)BOARD_HAS_BATTERY,
    .has_imu      = (bool)BOARD_HAS_IMU,
    // Runtime-only features, off unless this board has the screen space for
    // them (see docs/porting/capability-flags.md):
    // .is_round = true,
    // .has_media_controls = true,
    // .has_session_list = true,
};

const BoardCaps& board_caps(void) { return caps; }
