O objetivo deste documento é fornecer diretrizes para a criação de cenários de teste, de modo a padronizar o processo e garantir que os resultados obtidos sejam minimamente comparáveis.

Apesar da padronização proposta, encorajamos a experimentação e a adaptação dos cenários conforme a necessidade de cada contexto, desde que devidamente documentadas. Ressaltamos que este documento está em constante evolução e poderá ser atualizado à medida que novas práticas, aprendizados e necessidades forem identificados

## Cenário 1 – Consulta Intensiva (SELECT/GET)

Descrição:  
Simulação de 500 usuários simultâneos realizando exclusivamente operações de leitura, como consultas SELECT simples e também complexas (com múltiplas tabelas, joins, filtros e ordenações). O objetivo é avaliar a performance do banco sob alta demanda de leitura, típica de sistemas analíticos, dashboards e mecanismos de busca interna.

Foco:

* Tempo de resposta para consultas pesadas  
* Usar *ramp-up* para controlar o crescimento gradual da carga  
* Avaliar o tempo médio de resposta, erro de timeout ou falhas.  
* Monitorar uso de CPU, tempo de resposta e throughput (vazão) de consultas.

Expectativas:

* Tempo médio de resposta inferior a 500 ms  
* Taxa de sucesso mínima de 99%  
* Utilização de CPU abaixo de 85%

##  Cenário 2 – Escrita em Massa (INSERT/POST)

Descrição:

Testar a escalabilidade da aplicação ao receber várias requisições de escrita simultaneamente realizando operações de inserção de dados (INSERT), como envio de formulários, cadastros em lote, logs de eventos ou uploads de registros.

Foco:

* Tempo de inserção por operação  
* Vazão de dados gravados/min  
* Velocidade de commit em transações concorrentes  
* Consistência e integridade dos dados inseridos


Expectativas:

* Tempo médio de inserção por registro inferior a 400 ms  
* Pelo menos 99% das operações gravadas corretamente  
* Baixa taxa de I/O de escrita pendente no disco

## Cenário 3 – Atualizações Simultâneas (PUT)

Descrição:  
Simulação de 500 usuários simultâneos executando atualizações (UPDATE) em dados existentes, como alterações de status, correções de registros, ou reprocessamento de dados.

Foco:  
	

* Impacto no tempo de resposta durante o bloqueio de registros  
* Verificação de integridade após edições em massa  
* Monitorar uso de CPU e tempo de resposta.

Expectativas:

* Tempo médio de atualização inferior a 600 ms  
* Taxa de sucesso igual ou superior a 98%  
* Recursos de bloqueio e rollback eficientes para evitar corrupção de dados

## 

## Cenário 4 – Consulta e Escrita Concomitantes (MIXED SELECT/INSERT/UPDATE) \- Jefferson

Descrição:  
Simulação de carga mista onde 200 usuários executam consultas (SELECT), 200 realizam inserções (INSERT) e 100 efetuam atualizações (UPDATE) de forma simultânea. Esse cenário representa o ambiente real de um sistema em produção, com múltiplos tipos de operações ocorrendo em paralelo.

Foco:

* Avaliação do impacto da concorrência entre operações de leitura e escrita  
* Monitoramento de deadlocks, bloqueios e lentidão  
* Medição do tempo de resposta para cada tipo de operação

Expectativas:

* Tempo médio de resposta por operação inferior a 700 ms  
* Taxa de sucesso global mínima de 97%  
* Baixa incidência de deadlocks e timeouts

