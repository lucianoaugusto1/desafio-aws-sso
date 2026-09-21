#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exigir_aws

if [ "${FORCE:-0}" != "1" ]; then
  echo "Isto remove as stacks do laboratorio, incluindo o banco de dados."
  echo "A stack ${BOOTSTRAP_STACK} e preservada (OIDC e ECR, custo zero)."
  read -r -p "Digite 'destruir' para confirmar: " resposta
  [ "$resposta" = "destruir" ] || { echo "cancelado."; exit 0; }
fi

esvaziar_bucket() {
  local stack="$1" chave="$2" bucket
  bucket=$(stack_output "$stack" "$chave" 2>/dev/null) || return 0
  echo ">> esvaziando s3://${bucket}"
  aws s3 rm "s3://${bucket}" --recursive >/dev/null 2>&1 || true
}

remover_stack() {
  local nome="$1"
  if ! aws cloudformation describe-stacks --stack-name "$nome" >/dev/null 2>&1; then
    echo ">> ${nome} nao existe, pulando"
    return 0
  fi
  echo ">> removendo ${nome}"
  aws cloudformation delete-stack --stack-name "$nome"
  aws cloudformation wait stack-delete-complete --stack-name "$nome"
}

esvaziar_bucket "$GOVERNANCE_STACK" TrailBucketName
esvaziar_bucket "$FRONT_STACK" BucketName

remover_stack "$GOVERNANCE_STACK"
remover_stack "$FRONT_STACK"
remover_stack "$APP_STACK"
remover_stack "$DATA_STACK"
remover_stack "$NETWORK_STACK"

rm -f "${REPO_ROOT}/web/config.js"

echo
echo "laboratorio destruido. Custo corrente: zero."
