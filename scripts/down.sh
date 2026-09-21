#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exigir_aws

CLUSTER=$(stack_output "$APP_STACK" ClusterName)
SERVICE=$(stack_output "$APP_STACK" ServiceName)

echo ">> escalando o servico para 0"
aws ecs update-service \
  --cluster "$CLUSTER" --service "$SERVICE" \
  --desired-count 0 >/dev/null

aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"

echo "servico em 0 - Fargate parou de cobrar."
echo "O RDS continua ligado. Para zerar tudo, rode 'make destroy'."
