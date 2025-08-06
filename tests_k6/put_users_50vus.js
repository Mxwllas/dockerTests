import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export let options = {
    stages: [
        { duration: '3m', target: 50 },
    ],
    thresholds: {
        http_req_duration: ['avg<600'],
        http_req_failed: ['rate<0.02'],
        checks: ['rate>0.98'],
    }
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';

export default function () {
    // Primeiro cria um usuário
    const createPayload = JSON.stringify({
        name: `Usuário ${uuidv4()}`,
        username: `user_${uuidv4()}`,
        email: `${uuidv4()}@mail.com`,
        dateOfBirth: '1990-01-01',
        gender: 'Other',
        location: 'BR'
    });
    const params = { headers: { 'Content-Type': 'application/json' } };
    let createRes = http.post(`${BASE_URL}/users`, createPayload, params);
    let userId = '';
    if (createRes.status === 201 && createRes.json && createRes.json('id')) {
        userId = createRes.json('id');
    } else {
        // fallback: tenta extrair do Location header
        const location = createRes.headers['Location'];
        if (location) {
            userId = location.split('/').pop();
        }
    }
    if (!userId) {
        return;
    }
    // Atualiza o usuário
    const updatePayload = JSON.stringify({
        name: `Usuário Atualizado ${uuidv4()}`,
        username: `user_updated_${uuidv4()}`,
        email: `${uuidv4()}@mail.com`,
        dateOfBirth: '1991-01-01',
        gender: 'Other',
        location: 'BR'
    });
    let res = http.put(`${BASE_URL}/users/${userId}`, updatePayload, params);
    check(res, {
        'status 200': (r) => r.status === 200,
        'atualização < 600ms': (r) => r.timings.duration < 600,
    });
    sleep(1);
}
