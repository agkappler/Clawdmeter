#include "../../hal/board_caps.h"
#include "board.h"

static const BoardCaps caps = {
    .name = BOARD_NAME,
    .width = LCD_WIDTH,
    .height = LCD_HEIGHT,
    .button_count = 1,
    .has_rotation = false,
    .has_battery = false,
    .has_imu = false,
    .is_round = false,
    .has_media_controls = true,
    .has_session_list = true,
    .no_pwr_button = true,      // BOOT + RESET only
};

const BoardCaps& board_caps(void) { return caps; }
