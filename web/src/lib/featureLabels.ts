// Human-readable labels for the model's raw feature column names.
//
// The model carries 84 features that follow a small set of naming
// conventions (base feature + lag/roll suffix). Rather than enumerate
// each one, we map base names to display strings and apply regex
// transforms for the suffixes. New features automatically get a
// reasonable label as long as they follow the same pattern; anything
// unrecognized falls back to the raw name so the UI never crashes.

const BASE_LABELS: Record<string, string> = {
  air_temp_c_min: "Min air temperature",
  air_temp_c_mean: "Mean air temperature",
  air_temp_c_max: "Max air temperature",
  dew_point_c_mean: "Dew point",
  rh_pct_mean: "Relative humidity",
  wind_ms_mean: "Wind speed",
  shortwave_w_m2_mean: "Solar radiation",
  precip_mm_sum: "Precipitation",
  pressure_hpa_mean: "Surface pressure",
  cloud_pct_mean: "Cloud cover",
  water_temp_c: "Water temperature",
  streamflow_cfs: "Streamflow",
  wet_bulb_c: "Wet-bulb temperature",
  heat_index_c: "Heat index",
  water_thermal_stress: "Water thermal stress",
  heat_dose_7d: "Heat dose (7-day cumulative)",
  heat_dose_14d: "Heat dose (14-day cumulative)",
  doy_sin: "Day of year (cyclic, sin)",
  doy_cos: "Day of year (cyclic, cos)",
  water_site_id: "Water gauge ID",
};

const LAG_RE = /^(.+)_lag(\d+)$/;
const ROLL_RE = /^(.+)_roll(\d+)_(mean|max)$/;

function labelFor(base: string): string {
  return BASE_LABELS[base] ?? base;
}

/** Convert a raw feature column name into a display label.
 *  Unknown bases fall back to the raw name so adding features is safe. */
export function featureLabel(raw: string): string {
  const roll = raw.match(ROLL_RE);
  if (roll) {
    const [, base, n, kind] = roll;
    const suffix = kind === "max" ? "max" : "avg";
    return `${labelFor(base)} (${n}d ${suffix})`;
  }
  const lag = raw.match(LAG_RE);
  if (lag) {
    const [, base, n] = lag;
    return `${labelFor(base)} (${n}d ago)`;
  }
  return labelFor(raw);
}
