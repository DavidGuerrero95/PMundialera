# Prediction calibrator

Owns scoreline calibration, confidence, and primary prediction selection.

## Responsibilities

- Maintain one coherent scoreline distribution per match.
- Derive 1X2, over/under, BTTS, expected goals, and exact-score probabilities
  from that same distribution.
- Select `primary` by maximum GolPredictor expected points, not by modal exact
  score or narrative preference.
- Define `confidence` as the calibrated probability of the selected primary 1X2
  class.
- Treat draw as evidence-driven only; never use it as the default answer to
  missing data.
- Persist and audit `scoreline_distribution` and `expected_points_candidates`
  through SQLite research records.
