import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

// --- Opções do Teste de Carga (alinhadas com atualizacao_simultanea.js) ---
export let options = {
    vus: 500,
    duration: '1m',
    setupTimeout: '180s', // Aumenta o tempo máximo do setup
    thresholds: {
        http_req_failed: ['rate<0.02'], // Sucesso >= 98%
        http_req_duration: ['p(95)<600'], // 95% das requisições < 600ms
    },
};

// --- FASE 1: SETUP ---
// Cria a massa de dados inicial. Executado uma vez.
export function setup() {
    console.log('Iniciando Setup: criando usuários para o teste...');
    const baseUrl = __ENV.BASE_URL || 'http://localhost:3000';
    const userIds = [];
    // O número de usuários a criar deve ser igual ao número de VUs para o ciclo funcionar bem
    const numberOfUsersToCreate = options.vus;

    for (let i = 0; i < numberOfUsersToCreate; i++) {
        const userSuffix = uuidv4();
        const payload = JSON.stringify({
            name: `Setup User ${userSuffix}`,
            username: `setup_user_${userSuffix}`,
            email: `setup_user_${userSuffix}@test.com`
        });
        const params = { headers: { 'Content-Type': 'application/json' } };
        const res = http.post(`${baseUrl}/users`, payload, params);

        // Adiciona log para depuração - mostra o status e o corpo da resposta de CADA requisição
        console.log(`DEBUG (User ${i}): Status=${res.status}, Body=${res.body}`);

        // Verifica se a requisição foi bem-sucedida (status 201) e se o corpo da resposta é um JSON válido
        if (res.status === 201 && res.body) {
            try {
                const user = JSON.parse(res.body);
                if (user && user.id) {
                    userIds.push(user.id);
                }
            } catch (e) {
                console.error(`Falha ao parsear JSON da resposta para o usuário ${i}: ${e.message}`);
            }
        }
    }

    console.log(`--- Setup Concluído: ${userIds.length} de ${numberOfUsersToCreate} usuários criados.`);
    if (userIds.length < numberOfUsersToCreate) {
        console.warn('Atenção: Menos usuários foram criados do que o número de VUs. Alguns VUs podem não ter um usuário para atualizar.');
    }

    return { createdUserIds: userIds };
}

// --- FASE 2: TESTE DE UPDATE (CICLO DE REUTILIZAÇÃO) ---
export default function(data) {
    // Se o setup não criou usuários, ou se o VU atual não tem um usuário correspondente, ele para.
    if (!data.createdUserIds || data.createdUserIds.length === 0 || __VU > data.createdUserIds.length) {
        return;
    }

    // Cada VU pega um ID de usuário com base em seu próprio número de identificação (__VU).
    // O __VU é 1-based, então subtraímos 1 para pegar o índice do array (0-based).
    const userId = data.createdUserIds[__VU - 1];
    const url = `${__ENV.BASE_URL || 'http://localhost:3000'}/users/${userId}`;

    const updatePayload = JSON.stringify({
        name: `User Updated by VU ${__VU}`,
        location: `Location VU ${__VU}`
    });

    const params = { headers: { 'Content-Type': 'application/json' } };
    const res = http.put(url, updatePayload, params);

    check(res, {
        '[Update] Status é 200': (r) => r.status === 200,
    });

    sleep(1);
}
