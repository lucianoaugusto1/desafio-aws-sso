#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exigir_aws

CLUSTER=$(stack_output "$APP_STACK" ClusterName)
SERVICE=$(stack_output "$APP_STACK" ServiceName)

# 1. ARN da task em execucao
TASK=$(aws ecs list-tasks \
  --cluster "$CLUSTER" \
  --service-name "$SERVICE" \
  --desired-status RUNNING \
  --query 'taskArns[0]' --output text)

if [ "$TASK" = "None" ] || [ -z "$TASK" ]; then
  echo "erro: nenhuma task em execucao. Rode 'make up' primeiro." >&2
  exit 1
fi

# 2. Id da interface de rede anexada a task
ENI=$(aws ecs describe-tasks \
  --cluster "$CLUSTER" --tasks "$TASK" \
  --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value | [0]" \
  --output text)

# 3. IP publico associado a essa interface
aws ec2 describe-network-interfaces \
  --network-interface-ids "$ENI" \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text
