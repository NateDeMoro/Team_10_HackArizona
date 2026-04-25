"""Canonical schemas shared with api/. Copied into api/app/schemas.py at build time.

Contains only the constants populated tier-by-tier. Pydantic models will land
in later tiers when the API surface is filled in.
"""

# Canonical NRC unit name for Quad Cities Unit 1. NRC files use this exact
# string from 2005-onward; matching is performed case-insensitively at parse
# time so minor whitespace drift in older files cannot break ingestion.
CANONICAL_UNIT_QC1 = "Quad Cities 1"

# Earliest year the NRC publishes daily power-status files at the canonical
# URL. 1999 was specified in the plan; in practice files only exist from 2005.
NRC_EARLIEST_YEAR = 2005

# A unit is flagged is_outage=True for every day inside a run of >=N
# consecutive calendar days at exactly 0% power. Refueling outages typically
# span 14-30 days; 5 is conservative enough to also catch unplanned trips
# while excluding single-day curtailments that are weather-driven.
OUTAGE_MIN_CONSECUTIVE_DAYS = 5

# Pre-outage / coastdown detection. Operators ramp the reactor down over
# days-to-weeks before a planned refueling outage (and end-of-cycle fuel
# reactivity drives a longer "coastdown"); these days are not weather-driven
# and must be flagged so they can be excluded from training.
#
# Algorithm (applied per unit, only to outage runs of length
# >= REFUELING_OUTAGE_MIN_DAYS — i.e. real refueling cadence, not unplanned
# trips which have no planned ramp):
#   - Look at the PRE_OUTAGE_LOOKBACK_DAYS calendar days preceding the outage.
#   - Define baseline = max(power_pct) within that lookback.
#   - Walk backward day-by-day from the outage start, flagging is_pre_outage.
#   - Stop when PRE_OUTAGE_RECOVERY_RUN_LEN consecutive days are observed at
#     >= baseline - PRE_OUTAGE_TOLERANCE_PCT (the unit returned to full
#     output, so any prior dip is not part of this outage's coastdown).
#   - Cap at the lookback boundary if no recovery is found.
REFUELING_OUTAGE_MIN_DAYS = 14
PRE_OUTAGE_LOOKBACK_DAYS = 90
PRE_OUTAGE_TOLERANCE_PCT = 2
PRE_OUTAGE_RECOVERY_RUN_LEN = 3

# Fixed minimum number of days to flag as is_pre_outage immediately before
# every refueling outage. Acts as a floor on top of the adaptive coastdown
# detection above: when the algorithm finds a longer ramp it wins; when it
# finds none (abrupt drop or pre-uprate flat baseline) this guarantees the
# refueling outage still has a pre-outage exclusion window.
PRE_OUTAGE_MIN_BUFFER_DAYS = 14
