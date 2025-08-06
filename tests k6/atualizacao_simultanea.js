import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
    vus: 500,
    duration: '1m',
    setupTimeout: '180s', // aumenta o tempo máximo do setup
    thresholds: {
        http_req_failed: ['rate<0.02'], // Sucesso >= 98%
        http_req_duration: ['p(95)<600'], // 95% das requisições < 600ms
    },
};

const ids = Array.from({length: 500}, (_, i) => i + 1);
const nomes = ['João', 'Maria', 'Ana', 'Carlos', 'Paula', 'Lucas', 'Fernanda', 'Rafael', 'Juliana', 'Bruno'];
const generos = ['Male', 'Female', 'Other'];
const locais = ['SP', 'RJ', 'MG', 'RS', 'BA', 'PR', 'SC', 'PE', 'CE', 'DF'];

function randomItem(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
}

export function setup() {
    const baseUrl = __ENV.BASE_URL || 'http://localhost:3000';
    const batchSize = 50;
    const total = 500;
    let idsCriados = [];
    for (let i = 1; i <= total; i += batchSize) {
        let requests = [];
        for (let j = i; j < i + batchSize && j <= total; j++) {
            const payload = JSON.stringify({
                name: `${randomItem(nomes)} Teste${j}`,
                username: `user${j}`,
                email: `user${j}@teste.com`,
                dateOfBirth: `199${j % 10}-0${(j % 9) + 1}-1${(j % 8) + 1}`,
                gender: randomItem(generos),
                location: randomItem(locais)
            });
            const params = { headers: { 'Content-Type': 'application/json' } };
            requests.push({ method: 'POST', url: `${baseUrl}/users`, body: payload, params });
        }
        const responses = http.batch(requests);
        for (let r = 0; r < responses.length; r++) {
            if (responses[r].status === 201 || responses[r].status === 200) {
                idsCriados.push(i + r);
            } else {
                throw new Error(`Falha ao criar usuário ${i + r}: status ${responses[r].status}`);
            }
        }
    }
    // Confirma se todos foram criados
    if (idsCriados.length !== total) {
        throw new Error(`Nem todos os usuários foram criados: ${idsCriados.length} de ${total}`);
    }
    sleep(20); // Aguarda 20 segundos antes de iniciar o teste
    return { ids: idsCriados };
}

export default function (data) {
    const ids = data.ids;
    const id = ids[Math.floor(Math.random() * ids.length)];
    const url = `${__ENV.BASE_URL || 'http://localhost:3000'}/users/${id}`;
    const payload = JSON.stringify({
        name: `${randomItem(nomes)} Atualizado${id}`,
        username: `user${id}`,
        email: `user${id}@teste.com`,
        dateOfBirth: `199${id % 10}-0${(id % 9) + 1}-1${(id % 8) + 1}`,
        gender: randomItem(generos),
        location: randomItem(locais)
    });
    const params = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    let res = http.put(url, payload, params);
    check(res, {
        'status 200': (r) => r.status === 200,
    });
    sleep(1);
}
