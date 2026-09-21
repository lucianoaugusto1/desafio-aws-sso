# Desafio: subir infra AWS completa via CLI com agentes de IA

Laboratório prático de infraestrutura como código. O objetivo é **demonstrar e
ensinar** como provisionar, versionar e operar uma stack AWS inteira sem tocar
no Console — tudo por CloudFormation e AWS CLI, conduzido por um agente de IA.

A aplicação de exemplo é um microserviço de autenticação: uma API FastAPI com
usuários em PostgreSQL e um front estático que consome essa API.

> **Não use isto em produção.** Não há HTTPS, refresh token, rate limit nem
> endurecimento de segurança. É um laboratório com dados descartáveis.

## O que é provisionado

```
INTERNET
   |
   +--> [S3 website]  front estatico                        (HTTP)
   |          |  fetch
   |          v
   +--> [ECS Fargate, IP publico, :8000]  FastAPI
                   |  5432
                   v
            [RDS PostgreSQL 16, sem IP publico]
```

Mais a camada de governança: CloudWatch (logs, métricas e alarmes),
Secrets Manager (credencial do banco), CloudTrail (auditoria) e
AWS Budgets (teto de gasto).

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `infra/` | Os 6 templates CloudFormation, de `00-oidc` a `05-governance` |
| `api/` | Backend: FastAPI, Dockerfile, testes e compose com Postgres local |
| `web/` | Frontend estático: HTML e JavaScript puro, sem build |
| `scripts/` | `up.sh`, `down.sh`, `destroy.sh`, `task-ip.sh` |
| `docs/` | Spec de desenho e material do laboratório |
| `.github/workflows/` | `validate.yml` e `deploy.yml` |

## Custo

Fargate e Secrets Manager não têm free tier. A infra é **efêmera** por desenho:
o serviço ECS sobe com `desiredCount: 0` e só é escalado durante a demonstração.

| Estado | Custo |
|---|---|
| Destruída | $0,00 |
| No ar, serviço em 0 | ~$0,02/h (só RDS, ou $0 se a conta tem < 12 meses) |
| Demonstração de 3h com tudo ligado | ~$0,10 |

Um `AWS::Budgets::Budget` de US$ 5 com alertas em 50%, 80% e 100% existe como
rede de segurança contra esquecimento.

## Ciclo de operação

```bash
make up       # escala 0 -> 1, descobre o IP da task, regenera o config do front
make down     # escala -> 0, cessa a cobranca de Fargate, preserva a infra
make destroy  # remove as stacks 05 -> 01
```

## Fases

O laboratório avança em 6 fases, cada uma com uma verificação observável.
Nenhuma começa antes da anterior passar.

| Fase | Entrega | Verificação |
|---|---|---|
| 0 | AWS CLI, credenciais, repositório, stack `00-oidc` | `aws sts get-caller-identity` |
| 1 | `01-network` + `02-data` | RDS com status `available` |
| 2 | API FastAPI rodando local | `pytest` verde e login devolvendo JWT |
| 3 | `03-app` — imagem no ECR, task no Fargate | `/health` retorna `{"db":"ok"}` |
| 4 | `04-front` — site no S3 | Cadastro e login pelo navegador |
| 5 | CI/CD no GitHub Actions | Push na `main` republica sozinho |
| 6 | `05-governance` | Alarme por e-mail e evento no CloudTrail |

## Documentação

O desenho completo, com contrato dos endpoints, esquema do banco, decisões e
riscos, está em
[`docs/superpowers/specs/2026-09-21-aws-sso-infra-demo-design.md`](docs/superpowers/specs/2026-09-21-aws-sso-infra-demo-design.md).
