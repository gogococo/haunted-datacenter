-- Independent PostHog HogQL insights; no project token or game answers here.
-- Tables intentionally show no invented history before analytics rollout.

-- Players, shifts and outcomes · since rollout
SELECT uniqExactIf(distinct_id, event = 'haunted_shift_started') AS players_browsers,
 countIf(event = 'haunted_shift_started') AS shifts_started,
 countIf(event = 'haunted_shift_completed') AS escaped,
 countIf(event = 'haunted_shift_expired') AS time_expired
FROM events WHERE properties.environment = 'production' AND properties.practice = false;

-- Room timings · elapsed vs active minutes
SELECT properties.room AS room, count() AS completed,
 round(avg(toFloat(properties.elapsed_seconds))/60,1) AS average_solve_minutes,
 round(avg(toFloat(properties.active_seconds))/60,1) AS average_active_minutes
FROM events WHERE event='haunted_room_completed' AND properties.environment='production' AND properties.practice=false
GROUP BY room ORDER BY room;

-- Puzzle difficulty · hardest first (easiest at the bottom)
SELECT properties.step AS step, count() AS attempts,
 uniqExact(properties.game_id) AS shifts,
 countIf(properties.outcome IN ('failed','rejected')) AS unsuccessful,
 round(100.0*countIf(properties.outcome IN ('failed','rejected'))/count(),1) AS unsuccessful_percent
FROM events WHERE event='haunted_step_attempted' AND properties.environment='production' AND properties.practice=false
GROUP BY step ORDER BY unsuccessful_percent DESC, attempts DESC;

-- Room reach, completions and hint requests
SELECT properties.room AS room,
 countIf(event='haunted_room_entered') AS entered,
 countIf(event='haunted_room_completed') AS completed,
 countIf(event='haunted_hint_requested') AS hints
FROM events WHERE event IN ('haunted_room_entered','haunted_room_completed','haunted_hint_requested')
 AND properties.environment='production' AND properties.practice=false
GROUP BY room ORDER BY room;

-- Cloud latency and failures · separate from puzzle difficulty
SELECT properties.area AS area, properties.operation AS operation, count() AS requests,
 round(avg(toFloat(properties.duration_seconds)),2) AS average_seconds,
 countIf(properties.outcome='failed') AS errors
FROM events WHERE event='haunted_cloud_operation_completed' AND properties.environment='production' AND properties.practice=false
GROUP BY area,operation ORDER BY average_seconds DESC;

-- Training turnaround · submission to observed terminal status
SELECT properties.outcome AS outcome, count() AS jobs,
 round(avg(toFloat(properties.duration_seconds))/60,2) AS average_minutes
FROM events WHERE event='haunted_training_finished' AND properties.environment='production' AND properties.practice=false
GROUP BY outcome;
