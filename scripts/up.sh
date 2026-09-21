#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exigir_aws

CLUSTER=$(stack_output "$APP_STACK" ClusterName)
SERVICE=$(stack_output "$APP_STACK" ServiceName)

echo ">> escalando o servico para 1"
aws ecs update-service \
  --cluster "$CLUSTER" --service "$SERVICE" \
  --desired-count 1 >/dev/null

echo ">> aguardando a task estabilizar (pode levar alguns minutos)"
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"

IP=$("${REPO_ROOT}/scripts/task-ip.sh")
BUCKET=$(stack_output "$FRONT_STACK" BucketName)
SITE=$(stack_output "$FRONT_STACK" SiteUrl)

# O IP muda a cada deploy; e por isso que config.js nao e versionado.
echo ">> gravando o endereco da API em web/config.js"
printf 'window.API_URL = "http://%s:8000";\n' "$IP" > "${REPO_ROOT}/web/config.js"

echo ">> publicando o front"
aws s3 sync "${REPO_ROOT}/web/" "s3://${BUCKET}/" --delete

echo
echo "API:  http://${IP}:8000"
echo "Site: ${SITE}"
echo
echo "Ao terminar, rode 'make down' para parar de pagar Fargate."
