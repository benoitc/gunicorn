// HTTP stress driver. Select the scenario with SCENARIO and the target with
// TARGET; thresholds make the run exit non-zero if correctness or latency
// budgets are breached.
import { drive, scenario, thresholds } from './lib/checks.js';

const NAME = __ENV.SCENARIO || 'smoke';
const CHURN = NAME === 'churn';

export const options = {
  noConnectionReuse: CHURN,
  insecureSkipTLSVerify: (__ENV.INSECURE || '1') === '1',
  scenarios: { [NAME]: scenario(NAME) },
  thresholds: thresholds(),
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  drive();
}

export function handleSummary(data) {
  const out = {};
  out.stdout = textSummary(data);
  const file = __ENV.RESULT_FILE;
  if (file) out[`/results/${file}`] = JSON.stringify(data, null, 2);
  return out;
}

function textSummary(data) {
  const m = data.metrics;
  const failed = m.http_req_failed ? m.http_req_failed.values.rate : 0;
  const checks = m.checks ? m.checks.values.rate : 1;
  const dur = m.http_req_duration ? m.http_req_duration.values : {};
  const dropped = m.dropped_iterations ? m.dropped_iterations.values.count : 0;
  return [
    `scenario=${__ENV.SCENARIO} target=${__ENV.TARGET}`,
    `http_req_failed=${(failed * 100).toFixed(3)}%  checks=${(checks * 100).toFixed(3)}%`,
    `p95=${(dur['p(95)'] || 0).toFixed(1)}ms  p99=${(dur['p(99)'] || 0).toFixed(1)}ms  max=${(dur.max || 0).toFixed(1)}ms`,
    `dropped_iterations=${dropped}`,
    '',
  ].join('\n');
}
