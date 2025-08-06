#!/bin/bash
# Uso: ./monitor_metrics.sh <container_backend> <container_db> <intervalo_segundos> <saida>
CONTAINER_BACKEND=$1
CONTAINER_DB=$2
INTERVALO=${3:-2}
SAIDA=${4:-metrics.log}

echo "timestamp,host_cpu,host_mem,backend_cpu,backend_mem,db_cpu,db_mem" > $SAIDA

while true; do
  TS=$(date +%s)
  # CPU e MEM do host
  HOST_CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2 + $4}')
  HOST_MEM=$(free -m | awk '/Mem:/ {print $3}')
  # CPU/MEM dos containers (usa docker stats --no-stream)
  BACKEND_STATS=$(docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" | grep "$CONTAINER_BACKEND")
  DB_STATS=$(docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" | grep "$CONTAINER_DB")
  BACKEND_CPU=$(echo $BACKEND_STATS | cut -d',' -f2 | tr -d '%')
  BACKEND_MEM=$(echo $BACKEND_STATS | cut -d',' -f3 | awk '{print $1}')
  DB_CPU=$(echo $DB_STATS | cut -d',' -f2 | tr -d '%')
  DB_MEM=$(echo $DB_STATS | cut -d',' -f3 | awk '{print $1}')
  echo "$TS,$HOST_CPU,$HOST_MEM,$BACKEND_CPU,$BACKEND_MEM,$DB_CPU,$DB_MEM" >> $SAIDA
  sleep $INTERVALO
done
