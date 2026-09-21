#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exigir_aws

IMAGE_TAG="${IMAGE_TAG:-latest}"
DESIRED_COUNT="${DESIRED_COUNT:-1}"
ALERT_EMAIL="${ALERT_EMAIL:-}"

# --no-fail-on-empty-changeset: sem isto o comando sai com erro quando nada
# mudou, e um deploy repetido quebraria o pipeline.
deploy_stack() {
  local nome="$1" arquivo="$2"
  shift 2
  echo ">> ${nome}"
  aws cloudformation deploy \
    --stack-name "$nome" \
    --template-file "${REPO_ROOT}/infra/${arquivo}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset \
    "$@"
}

deploy_stack "$NETWORK_STACK" 01-network.yaml

deploy_stack "$DATA_STACK" 02-data.yaml \
  --parameter-overrides "NetworkStackName=${NETWORK_STACK}"

deploy_stack "$APP_STACK" 03-app.yaml \
  --parameter-overrides \
    "BootstrapStackName=${BOOTSTRAP_STACK}" \
    "NetworkStackName=${NETWORK_STACK}" \
    "DataStackName=${DATA_STACK}" \
    "ImageTag=${IMAGE_TAG}" \
    "DesiredCount=${DESIRED_COUNT}"

deploy_stack "$FRONT_STACK" 04-front.yaml

if [ -n "$ALERT_EMAIL" ]; then
  deploy_stack "$GOVERNANCE_STACK" 05-governance.yaml \
    --parameter-overrides \
      "AppStackName=${APP_STACK}" \
      "AlertEmail=${ALERT_EMAIL}"
else
  echo ">> ${GOVERNANCE_STACK} pulada: defina ALERT_EMAIL para criar alarmes e budget"
fi

echo
echo "stacks no ar:"
aws cloudformation describe-stacks \
  --query "Stacks[?starts_with(StackName, '${PROJECT}')].[StackName,StackStatus]" \
  --output table
