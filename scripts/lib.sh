#!/usr/bin/env bash
# Funcoes e nomes compartilhados pelos scripts do laboratorio.
# Este arquivo e carregado com "source", nunca executado direto.

PROJECT="${PROJECT:-sso-lab}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION

BOOTSTRAP_STACK="${PROJECT}-bootstrap"
NETWORK_STACK="${PROJECT}-network"
DATA_STACK="${PROJECT}-data"
APP_STACK="${PROJECT}-app"
FRONT_STACK="${PROJECT}-front"
GOVERNANCE_STACK="${PROJECT}-governance"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exigir_aws() {
  if ! command -v aws >/dev/null 2>&1; then
    echo "erro: AWS CLI nao encontrada. Veja a Fase 0 no README." >&2
    exit 1
  fi
  if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "erro: credenciais AWS ausentes ou invalidas. Veja a Fase 0 no README." >&2
    exit 1
  fi
}

# stack_output <nome-da-stack> <chave-do-output>
stack_output() {
  local stack="$1" chave="$2" valor
  valor=$(aws cloudformation describe-stacks \
    --stack-name "$stack" \
    --query "Stacks[0].Outputs[?OutputKey=='${chave}'].OutputValue" \
    --output text 2>/dev/null)
  if [ -z "$valor" ] || [ "$valor" = "None" ]; then
    echo "erro: output '${chave}' nao encontrado na stack '${stack}'" >&2
    return 1
  fi
  printf '%s\n' "$valor"
}
