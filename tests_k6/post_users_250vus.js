import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export let options = {
    vus: 250,
    duration: '3m',
    thresholds: {
        http_req_duration: ['avg<400'],
        http_req_failed: ['rate<0.01'],
        checks: ['rate>0.99'],
    }
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';

export default function () {
    const payload = JSON.stringify({
        name: `Usuário ${uuidv4()}`,
        username: `user_${uuidv4()}`,
        email: `${uuidv4()}@mail.com`,
        dateOfBirth: '1990-01-01',
        gender: 'Other',
        location: 'BR'
    });
    const params = { headers: { 'Content-Type': 'application/json' } };
    let res = http.post(`${BASE_URL}/users`, payload, params);
    check(res, {
        'status 201': (r) => r.status === 201,
        'inserção < 400ms': (r) => r.timings.duration < 400,
    });
    sleep(1);
}
