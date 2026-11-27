// Shared checks, thresholds, and scenario builders for the stress suite.
import http from 'k6/http';
import { check } from 'k6';
import crypto from 'k6/crypto';

const TARGET = __ENV.TARGET || 'http://localhost:8000';
const EXPECT_PROTO = __ENV.EXPECT_PROTO || '';        // e.g. HTTP/1.1, HTTP/2.0
const INSECURE = (__ENV.INSECURE || '1') === '1';
const FAIL_BUDGET = parseFloat(__ENV.FAIL_BUDGET || '0'); // allowed error rate
const MAX_P95 = parseInt(__ENV.MAX_P95 || '3000', 10);    // ms
const MAX_P99 = parseInt(__ENV.MAX_P99 || '8000', 10);    // ms

export const params = { insecureSkipTLSVerify: INSECURE };

// A request id unique per iteration so a response carrying a different id
// proves cross-request data leakage.
function reqId() {
  return `${__VU}-${__ITER}-${Math.random().toString(36).slice(2)}`;
}

export function thresholds() {
  return {
    http_req_failed: [`rate<=${FAIL_BUDGET}`],
    checks: [`rate>=${1 - FAIL_BUDGET}`],
    http_req_duration: [`p(95)<${MAX_P95}`, `p(99)<${MAX_P99}`],
    dropped_iterations: ['count>=0'], // reported so LG saturation is visible
  };
}

// One representative request mix. Every response is checked for status, the
// echoed request id, the negotiated protocol, and (for bodies we can predict)
// an exact checksum.
export function drive() {
  const id = reqId();
  const headers = { 'X-Request-Id': id };
  const roll = Math.random();

  if (roll < 0.4) {
    const res = http.get(`${TARGET}/small`, { headers, ...params });
    verify(res, id, 200);
  } else if (roll < 0.7) {
    const body = crypto.randomBytes(1024 + Math.floor(Math.random() * 8192));
    const res = http.post(`${TARGET}/echo`, body, {
      headers: { ...headers, 'Content-Type': 'application/octet-stream' },
      responseType: 'binary', ...params,
    });
    const ok = verify(res, id, 200);
    check(res, {
      'echo body intact': (r) => new Uint8Array(r.body).length === body.byteLength,
      'echo checksum matches': (r) =>
        r.headers['X-Body-Sha256'] === crypto.sha256(body, 'hex'),
    }) && ok;
  } else if (roll < 0.85) {
    const size = 65536;
    const res = http.get(`${TARGET}/large?size=${size}`, { headers, responseType: 'binary', ...params });
    verify(res, id, 200);
    check(res, {
      'large size matches': (r) => new Uint8Array(r.body).length === size,
      'large checksum matches': (r) =>
        r.headers['X-Body-Sha256'] === crypto.sha256(r.body, 'hex'),
    });
  } else {
    const res = http.get(`${TARGET}/meta?probe=1`, { headers, ...params });
    verify(res, id, 200);
    check(res, { 'meta is json': (r) => (r.headers['Content-Type'] || '').includes('json') });
  }
}

function verify(res, id, status) {
  return check(res, {
    'status is expected': (r) => r.status === status,
    'request id echoed': (r) => r.headers['X-Request-Id'] === id,
    'protocol as negotiated': (r) => !EXPECT_PROTO || r.proto === EXPECT_PROTO,
  });
}

// Scenario executor definitions, selected by name.
export function scenario(name) {
  const RATE = parseInt(__ENV.RATE || '50', 10);
  const DURATION = __ENV.DURATION || '30s';
  const VUS = parseInt(__ENV.VUS || '10', 10);
  const MAXVUS = parseInt(__ENV.MAXVUS || '200', 10);

  switch (name) {
    case 'smoke':
      return { executor: 'constant-vus', vus: 2, duration: __ENV.DURATION || '10s' };
    case 'constant':
      return {
        executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s',
        duration: DURATION, preAllocatedVUs: VUS, maxVUs: MAXVUS,
      };
    case 'ramping':
      return {
        executor: 'ramping-arrival-rate', startRate: 10, timeUnit: '1s',
        preAllocatedVUs: VUS, maxVUs: MAXVUS,
        stages: [
          { target: RATE, duration: '15s' },
          { target: RATE * 2, duration: '30s' },
          { target: RATE * 4, duration: '30s' },
          { target: 0, duration: '10s' },
        ],
      };
    case 'spike':
      return {
        executor: 'ramping-arrival-rate', startRate: RATE, timeUnit: '1s',
        preAllocatedVUs: VUS, maxVUs: MAXVUS,
        stages: [
          { target: RATE, duration: '10s' },
          { target: RATE * 10, duration: '10s' },
          { target: RATE, duration: '10s' },
        ],
      };
    case 'churn':
      // New connection per iteration exercises accept/keepalive churn.
      return { executor: 'constant-vus', vus: VUS, duration: DURATION };
    case 'soak':
      return {
        executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s',
        duration: __ENV.DURATION || '30m', preAllocatedVUs: VUS, maxVUs: MAXVUS,
      };
    default:
      throw new Error(`unknown scenario ${name}`);
  }
}
