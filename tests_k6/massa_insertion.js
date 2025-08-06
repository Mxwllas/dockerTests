import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export let options = {
    stages: [
        { duration: '1m', target: 500 }, // 500 usuários simultâneos por 1 minuto
    ],
    thresholds: {
        http_req_duration: ['avg<400'], // tempo médio de inserção < 400ms
        http_req_failed: ['rate<0.01'], // menos de 1% de falhas
        checks: ['rate>0.99'],          // pelo menos 99% das operações gravadas corretamente
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
