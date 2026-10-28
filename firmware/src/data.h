#pragma once
#include <Arduino.h>

// Market quotes for the center rotator (see ui.cpp). The daemon pre-formats the
// price string so currency/precision decisions stay host-side; only the percent
// change comes across as a number, because the firmware colors it by sign.
#define MAX_QUOTES 3

struct QuoteData {
    char  sym[10];    // ticker as it should be displayed, e.g. "AMZN"
    char  price[14];  // formatted by the daemon, e.g. "$212.34"
    float chg_pct;    // percent change vs. previous close
    bool  has_chg;    // false when the daemon couldn't compute a change
};

// Software quote of the day, scraped host-side. Sized to the longest text the
// rotator can wrap into its panel at its smallest font — the quote is never
// shortened to fit a BLE write (the daemon sends it as a separate write when it
// has to), so this buffer has to hold whatever the daemon considers sendable.
#define MAX_QOD_TEXT 320
#define MAX_QOD_AUTHOR 32

// Claude Code session status, sent by the daemon as its own "ss" write (see
// daemon/session_status.py). Sizes match the daemon's HOST_MAX / NAME_MAX /
// MAX_SESSIONS; text is ASCII-folded host-side for the bundled fonts.
#define MAX_SESSIONS 6
enum session_state_t : uint8_t {
    SESSION_WORKING = 0,
    SESSION_NEEDS_YOU = 1,
    SESSION_YOUR_TURN = 2,
    SESSION_STALE = 3,
};

struct SessionData {
    char host[9];     // machine tag, e.g. "wsl"
    char name[21];    // session title or project folder, e.g. "api#2"
    uint8_t state;    // session_state_t
};

struct UsageData {
    float session_pct;       // utilization 0-100 (5h window Pro/Max; spending % Enterprise)
    int session_reset_mins;  // minutes until reset
    float weekly_pct;        // 7-day utilization (Pro/Max only; 0 for Enterprise)
    int weekly_reset_mins;   // minutes until weekly reset (Pro/Max only)
    char status[16];         // "allowed", "limited", etc.
    bool chime;              // play the session-reset chime; false unless daemon opts in
    bool enterprise;         // true = Enterprise spending-limit account
    int time_pct;            // 0-100: fraction of billing period elapsed (Enterprise)
    int period_days;         // total billing period length in days (Enterprise)
    char reset_date[12];     // formatted reset date e.g. "Jul 1" (Enterprise)
    long clock_epoch;        // local wall-clock epoch (s) from daemon; 0 = not provided
    int  clock_fmt;          // 12 or 24 (hour format from daemon); defaults to 24
    // Minutes to add to clock_epoch to get US Eastern / UTC, so the clock card
    // can show both in small print without the device knowing any tz rules.
    // 0 means "same as local" — which is also what an older daemon that doesn't
    // send them produces, and in both cases that line is simply not rendered.
    int  clock_et_off_min;
    int  clock_utc_off_min;
    QuoteData quotes[MAX_QUOTES];  // market quotes from the daemon (may be empty)
    int  quote_count;        // number of populated entries in quotes[]
    char qod_text[MAX_QOD_TEXT];      // quote of the day; empty = not provided
    char qod_author[MAX_QOD_AUTHOR];  // its author; may be empty even with text
    // Session status. Only an "ss" field ever changes these, never a usage
    // payload without one, so a usage write can't wipe the list.
    SessionData sessions[MAX_SESSIONS];
    int  session_count;
    bool ok;                 // data parse succeeded
    bool valid;              // false until first successful parse
};
