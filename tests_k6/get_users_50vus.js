import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
    stages: [
        { duration: '3m', target: 50 },
    ],
    thresholds: {
        http_req_duration: ['avg<500'],
        http_req_failed: ['rate<0.01'],
        checks: ['rate>0.99'],
    }
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';

export default function () {
    let res = http.get(`${BASE_URL}/users`);
    check(res, {
        'status 200': (r) => r.status === 200,
        'consulta < 500ms': (r) => r.timings.duration < 500,
    });
    sleep(1);
}
