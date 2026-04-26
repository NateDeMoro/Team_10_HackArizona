# Problems Encountered

This document summarizes the substantive problems encountered while building the Nuclear Cooling-Water Derating Forecaster, the diagnosis of each, and how it was resolved.

## 1. Mode Collapse on the Dominant Output Value

The first XGBoost regressor, trained with an unweighted squared-error objective, mode-collapsed to predicting the dominant target value (100% capacity) on essentially every day. Mean absolute error on the dip slice exceeded 21 percentage points, making the model useless for its actual purpose.

**Resolution.** A dip-weighted sample-weight scheme was introduced for the point fit only: `weight = 1 + 0.5 * max(0, (100 - y) / 5)`. This pulls the model away from the dominant mode at the cost of roughly doubling full-slice MAE — an acceptable trade-off because the product cares about correctly predicting derating events, not the boring days.

## 2. Quantile Models Did Not Behave as Expected

Several attempts to publish a downside uncertainty band via quantile regression failed. The q90 booster was useless for a derating forecaster (no upside-asymmetry value), q25 added no information beyond q10, and the conformally-calibrated q10 ended up above the dip-weighted point on most days because the dip-weighted point under-predicts on roughly 95% of validation rows by design.

**Resolution.** Replaced the asymmetric quantile band with a symmetric residual band centered on the calibrated point: per-horizon `delta_h` is the 80th-percentile of absolute validation residuals. Empirical coverage on the 2023+ test split lands between 0.72 and 0.83 across horizons, close to the 0.80 target.

## 3. Systematic Bias from the Dip-Weighted Objective

The dip-weighted point objective left a residual 3 to 5 percentage-point negative bias on the dominant 100% mode. A naive uniform isotonic calibration learned the wrong correction — it pulled dip-day predictions back up toward 100, destroying dip recall.

**Resolution.** A per-horizon isotonic calibrator is fit on validation data and applied conditionally only when the raw prediction is at or above the dip threshold. On Quad Cities Unit 1 at the 7-day horizon, this reduced 100%-mode bias from -5.15pp to -3.16pp and full-slice MAE from 5.35 to 3.48 without harming dip detection.

## 4. NRC Power-Status Data Schema Drift

The NRC's historical reactor power-status files have inconsistent formatting across years. A strict parser would have failed silently on partial-year coverage.

**Resolution.** Built a tolerant parser that logs and skips malformed rows, asserting at least a 95% parse rate per year. Outage periods (14+ consecutive days at 0%) are flagged with a boolean rather than imputed or dropped.

## 5. USGS Water-Temperature Gauge Coverage

USGS water-temperature infrastructure is patchier than its catalog suggests. Multiple gauges that appeared active had no recent data: a Columbia River gauge near a candidate plant was decommissioned in 2022, an Oswego gauge near FitzPatrick was pulled in late 2024, and the upper Mississippi has no continuous daily-value temperature record post-1999. Many gauges also remove their temperature sensors over winter.

**Resolution.** Plant selection now requires a live recency check on every candidate gauge, not just a horizon look-up. Within a chosen plant, temperature and flow can come from different gauges, declared as per-parameter site lists in the plant registry. Missing values are left null rather than imputed; XGBoost handles missingness natively.

## 6. The Dip-Event Population Is Mostly Not Weather-Driven

Of 28 sub-95% capacity events in the Quad Cities Unit 1 2023+ test set, only 1 is plausibly weather-driven and 4 are marginal. The remaining events occurred on cold-water or cold-air days where cooling-water physics rules out a thermal-discharge derating — these are operator events (scrams, valve tests, grid-following) that the model architecturally cannot predict.

**Resolution.** Documented explicitly in the backtest report so a reader cannot interpret "model beats baselines on dips" without context. A second plant — Byron Unit 1 on the Rock River, which has a 4.47x summer/winter dip ratio — was added specifically because its weather signature is the strongest cleanly available in the historical record outside of TVA.

## 7. Single Alert Threshold Was Useless in Practice

A single 95% capacity threshold fired the red alert on roughly 99% of days because the dip-weighted point predictions cluster between 92 and 97. An always-red badge carries no information.

**Resolution.** Decoupled the metric threshold from the UI threshold. The metric threshold (`DIP_THRESHOLD_PCT = 95`) is held stable for cross-iteration comparability. The UI uses a three-tier scheme — operational at 95 and above, watch between 90 and 95, alert below 90 — which fires red on roughly 41% of test days and catches the actual sub-95% dips with a mix of red and yellow.

## 8. Historical-Forecast API Coverage Window

The original Tier 4 plan assumed Open-Meteo's archived numerical-weather-prediction runs would extend across the full backtest period. They begin on 2016-01-01, which means historical demonstration dates earlier than that — including the 2012 Midwest heatwave — cannot use the actual forecast that would have been available on the day.

**Resolution.** Each backtest row is tagged with a `ForecastSource` value (`live`, `historical_nwp`, or `era5_fallback`). Pre-2016 dates fall back to ERA5 reanalysis with the hindsight caveat made explicit in the report rather than hidden.

## 9. Persistence Baseline Beats the Model on Full-Slice MAE

Persistence — predicting that tomorrow's capacity equals today's — beats the model on full-slice MAE (roughly 1.0 versus 6.8 at the 1-day horizon). At face value this looks like a failure.

**Resolution.** Persistence cannot anticipate a future dip; that limitation is the entire reason this product exists. The backtest report leads with dip-event MAE, where the model beats both climatology and persistence at every horizon, and relegates full-slice MAE to a footer with a clear note explaining why it is not the metric being optimized.

## 10. Forecast Architecture Simplification

The original plan called for the model to consume forward-looking weather forecasts at each prediction horizon as input features, which would have required a future-water-temperature sub-model and complex feature alignment.

**Resolution.** Each per-horizon model was instead trained to consume features only at the run date, learning directly how today's conditions correlate with capacity at a given lead time. This collapsed inference to a single feature row per run date, removed the sub-model entirely, and made cached ERA5 features sufficient for all historical run dates.
