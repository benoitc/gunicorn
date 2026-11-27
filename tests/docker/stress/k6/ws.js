// WebSocket stress driver for the asgi worker. Opens connections, echoes text,
// checks integrity, and paces itself so the smoke load is a realistic handshake
// rate rather than a connection flood. Raise VUS / drop SLEEP for nightly load.
import ws from 'k6/ws';
import { check, sleep } from 'k6';

const TARGET = __ENV.WS_TARGET || 'ws://localhost:8463';
const DURATION = __ENV.DURATION || '15s';
const VUS = parseInt(__ENV.VUS || '10', 10);
const SLEEP = parseFloat(__ENV.WS_SLEEP || '0.3');
const FAIL_BUDGET = parseFloat(__ENV.FAIL_BUDGET || '0');

export const options = {
  scenarios: { ws: { executor: 'constant-vus', vus: VUS, duration: DURATION } },
  thresholds: { checks: [`rate>=${1 - FAIL_BUDGET}`] },
};

export default function () {
  const text = `hello-${__VU}-${__ITER}-${Math.random().toString(36).slice(2)}`;
  const res = ws.connect(`${TARGET}/ws/echo`, {}, (socket) => {
    let got = 0;
    socket.on('open', () => socket.send(text));
    socket.on('message', (msg) => {
      check(msg, { 'ws text echoed intact': (m) => m === text });
      got += 1;
      socket.close();
    });
    socket.setTimeout(() => {
      check(got, { 'ws received a reply': (g) => g > 0 });
      socket.close();
    }, 5000);
  });
  check(res, { 'ws handshake 101': (r) => r && r.status === 101 });
  if (SLEEP > 0) sleep(SLEEP);
}

export function handleSummary(data) {
  const out = { stdout: '' };
  const c = data.metrics.checks ? data.metrics.checks.values.rate : 1;
  out.stdout = `ws checks=${(c * 100).toFixed(3)}% sessions=${
    data.metrics.ws_sessions ? data.metrics.ws_sessions.values.count : 0}\n`;
  const file = __ENV.RESULT_FILE;
  if (file) out[`/results/${file}`] = JSON.stringify(data, null, 2);
  return out;
}
