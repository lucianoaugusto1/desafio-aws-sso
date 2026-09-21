# Laboratório: subir infra AWS completa via CLI com agentes de IA

**Data:** 2026-09-21
**Status:** aprovado
**Autor:** sessão de brainstorming Claude Code

---

## 1. Objetivo

Demonstrar e ensinar como provisionar, versionar e operar uma infraestrutura
AWS completa usando exclusivamente a linha de comando, conduzida por um agente
de IA. O artefato final é um repositório que qualquer pessoa consegue clonar,
executar e entender.

O sistema de exemplo é um microserviço de autenticação ("SSO"): uma API FastAPI
com usuários em PostgreSQL, servida por um front estático.

**O aprendizado é o produto.** A aplicação existe para dar propósito à infra,
não o contrário.

## 2. Não-escopo

Cortado deliberadamente para manter os templates legíveis:

- HTTPS, certificados, domínio próprio
- Application Load Balancer, CloudFront, NAT Gateway, subnets privadas
- Alta disponibilidade (Multi-AZ), auto scaling, rollback automatizado
- OAuth2 federado, refresh tokens, JWKS, rotação de chave, rate limiting
- Migrations versionadas (Alembic), build de front-end (bundler, framework)
- Endurecimento de segurança em geral

Este repositório **não é adequado para produção** e diz isso no README.

## 3. Restrições

| Restrição | Consequência no desenho |
|---|---|
| Região `us-east-1` | Menor preço, todos os serviços disponíveis |
| Conta pessoal com AdministratorAccess | Sem necessidade de mapear permissões restritas |
| Custo próximo de zero | Infra efêmera; Fargate com `desiredCount: 0` em repouso |
| Sem HTTPS | Front e API ambos em HTTP puro (sem mixed content) |
| CLI como interface única | Nenhum passo do laboratório usa o Console AWS |

### Custo real

Fargate e Secrets Manager não têm free tier. Uma sessão de demonstração de
3 horas com tudo ligado custa aproximadamente:

| Item | 3h |
|---|---|
| Fargate 0.25 vCPU / 0.5 GB | $0,037 |
| RDS `db.t4g.micro` + 20 GB | $0,06 — ou $0,00 se a conta tiver menos de 12 meses |
| Secrets Manager (rateado por hora) | $0,002 |
| S3, ECR, CloudWatch, CloudTrail, Budgets | $0,00 (free tier) |
| **Total** | **≈ $0,10** |

Com as stacks destruídas, o custo é $0,00. O `AWS::Budgets::Budget` de $5/mês
existe como rede de segurança contra esquecimento.

## 4. Arquitetura

```
INTERNET
   |
   +--> [S3 website]  index.html + app.js + config.js        (HTTP)
   |          |
   |          | fetch(window.API_URL)
   |          v
   +--> [ECS Fargate task, IP publico, :8000]  FastAPI
                   |
                   | 5432 (somente de sg-api)
                   v
            [RDS PostgreSQL 16, sem IP publico]
```

Tudo dentro de uma VPC `10.0.0.0/16` com duas subnets públicas
(`us-east-1a`, `us-east-1b`) e um Internet Gateway. Não há NAT Gateway: a task
Fargate recebe IP público e por isso consegue puxar a imagem do ECR sozinha.

O RDS fica em subnet pública porém com `PubliclyAccessible: false` — não recebe
IP público e o `sg-db` só aceita tráfego originado no `sg-api`.

A segunda subnet existe apenas porque um `DBSubnetGroup` exige no mínimo duas
zonas de disponibilidade.

## 5. Stacks CloudFormation

Seis templates independentes, ligados por `Outputs` e `Fn::ImportValue`.
Prefixo de nome: `sso-lab-`.

| Arquivo | Stack | Recursos | Exports |
|---|---|---|---|
| `infra/00-oidc.yaml` | `sso-lab-oidc` | OIDC provider do GitHub, role de deploy | `DeployRoleArn` |
| `infra/01-network.yaml` | `sso-lab-network` | VPC, 2 subnets, IGW, route table, `sg-api`, `sg-db` | `VpcId`, `SubnetIds`, `ApiSgId`, `DbSgId` |
| `infra/02-data.yaml` | `sso-lab-data` | `DBSubnetGroup`, `DBInstance` | `DbEndpoint`, `DbPort`, `DbSecretArn` |
| `infra/03-app.yaml` | `sso-lab-app` | ECR, ECS Cluster, TaskDefinition, Service, LogGroup, execution role, task role | `ClusterName`, `ServiceName`, `EcrUri` |
| `infra/04-front.yaml` | `sso-lab-front` | Bucket S3 com website hosting + bucket policy | `SiteUrl`, `BucketName` |
| `infra/05-governance.yaml` | `sso-lab-governance` | CloudTrail + bucket, tópico SNS, 2 alarmes, 1 budget | — |

Ordem de deploy: `00 → 01 → 02 → 03 → 04 → 05`.
Ordem de destruição: exatamente a inversa.

### Decisões por stack

**`02-data`** usa `ManageMasterUserPassword: true`. O próprio RDS gera a senha,
cria o segredo no Secrets Manager e faz a rotação. Nenhuma senha aparece em
template, parâmetro ou variável de ambiente.

**`03-app`** expõe `DesiredCount` como parâmetro com **default `0`**. A stack
sobe sem cobrar Fargate; o serviço só é escalado para 1 durante a demonstração.
O `LogGroup` tem retenção de 7 dias para permanecer dentro dos 5 GB grátis do
CloudWatch Logs.

A *task role* recebe permissão de `secretsmanager:GetSecretValue` restrita ao
ARN do segredo exportado por `02-data`. A *execution role* usa a policy
gerenciada `AmazonECSTaskExecutionRolePolicy`.

**`04-front`** desliga o Block Public Access do bucket e aplica policy de
leitura pública — necessário para o website endpoint do S3, que serve em HTTP.

## 6. A API de SSO

FastAPI, aproximadamente 150 linhas de código de aplicação.

### Contrato

| Método | Rota | Entrada | Saída |
|---|---|---|---|
| `GET` | `/health` | — | `{"status":"ok","db":"ok"}` — executa `SELECT 1` no RDS |
| `POST` | `/auth/register` | `{email, password}` | `201` com `{id, email}`; `409` se já existe |
| `POST` | `/auth/login` | `{email, password}` | `{access_token, token_type:"bearer", expires_in:3600}`; `401` se inválido |
| `GET` | `/auth/me` | header `Authorization: Bearer <jwt>` | `{id, email, created_at}`; `401` se token ausente, inválido ou expirado |

`GET /health` é o endpoint que prova que a infra inteira funciona: ele só
responde `db: ok` se a task Fargate conseguiu ler o segredo no Secrets Manager
e alcançar o RDS pelo security group.

### Modelo de dados

Tabela única `users`:

| Coluna | Tipo |
|---|---|
| `id` | `integer`, PK, autoincrement |
| `email` | `varchar(255)`, único, indexado |
| `password_hash` | `varchar(255)` |
| `created_at` | `timestamptz`, default `now()` |

Criada no startup da aplicação com `Base.metadata.create_all()`. Sem Alembic.

### Segredos e configuração

Na inicialização, a aplicação lê do Secrets Manager:

1. O segredo gerenciado pelo RDS (usuário, senha, host, porta, dbname) para
   montar a URL de conexão.
2. Um segundo segredo, criado por `03-app`, contendo a chave de assinatura do
   JWT.

Ambos os ARNs chegam ao container por variável de ambiente na TaskDefinition.

JWT assinado em HS256, validade de 1 hora. Senha com hash bcrypt.

### Testes

`pytest` com SQLite em memória substituindo o PostgreSQL via override de
dependência do FastAPI. Cobre: registro, registro duplicado, login correto,
login com senha errada, `/auth/me` com token válido e com token inválido.

## 7. Front estático

Três arquivos, sem etapa de build:

- `web/index.html` — formulário de cadastro e de login, área que mostra o
  resultado de `/auth/me`
- `web/app.js` — chamadas `fetch` e armazenamento do token em `localStorage`
- `web/config.js` — contém apenas `window.API_URL = "http://<ip>:8000"`

`config.js` **não é versionado**. Ele é gerado pelo pipeline (e por
`scripts/up.sh`) a cada vez que a task ganha um IP novo, e enviado ao S3 junto
com os demais arquivos.

## 8. CI/CD

GitHub Actions com autenticação OIDC. Nenhuma chave de acesso é armazenada:
a role criada em `00-oidc.yaml` confia no provider
`token.actions.githubusercontent.com` com condição restrita ao repositório.

| Workflow | Gatilho | Passos |
|---|---|---|
| `validate.yml` | `push` e `pull_request` | `cfn-lint` nos 6 templates; `ruff check`; `pytest`; `docker build` (sem push) |
| `deploy.yml` | `push` na `main` | assume role via OIDC → login no ECR → build e push da imagem com tag do SHA → `aws cloudformation deploy` das stacks 01→05 → escala o serviço → descobre o IP público da task → gera `config.js` → `aws s3 sync` do front |

### Descoberta do IP da task

Como não há ALB, o endereço da API muda a cada deploy. O passo de descoberta,
usado tanto pelo workflow quanto por `scripts/up.sh`:

1. `aws ecs list-tasks --cluster <c> --service-name <s>` → ARN da task
2. `aws ecs describe-tasks` → ID da ENI no campo `attachments`
3. `aws ec2 describe-network-interfaces` → `Association.PublicIp`

## 9. Governança

**CloudWatch** — log group `/ecs/sso-lab-api` com retenção de 7 dias; metric
filter contando ocorrências de `ERROR`; alarme de CPU acima de 80% na task e
alarme de mais de 5 erros em 5 minutos. Ambos publicam em um tópico SNS com
assinatura por e-mail (endereço é parâmetro da stack).

**CloudTrail** — uma trilha de management events gravando em bucket S3 próprio
com lifecycle de expiração em 7 dias. Management events na primeira trilha são
gratuitos. Serve para a demonstração de auditoria: "quem criou este recurso e
quando".

**Budgets** — orçamento mensal de US$ 5 com notificações em 50%, 80% e 100%,
tanto para gasto real quanto previsto, no mesmo e-mail.

## 10. Ciclo de vida

Três comandos formam o roteiro operacional da demonstração:

| Comando | Efeito |
|---|---|
| `make up` | Escala o serviço de 0 para 1, aguarda estabilizar, descobre o IP, regenera `config.js` e sincroniza com o S3 |
| `make down` | Escala o serviço para 0 — cessa a cobrança de Fargate, preserva toda a infra |
| `make destroy` | Remove as stacks 05→01, esvaziando antes os buckets do front e do CloudTrail |

`make destroy` preserva `sso-lab-oidc`, que não custa nada e é reaproveitada.

## 11. Estrutura do repositório

```
.
|-- Makefile
|-- README.md                      roteiro guiado do laboratorio
|-- docs/superpowers/specs/        este documento
|-- infra/                         00-oidc .. 05-governance (.yaml)
|-- api/
|   |-- Dockerfile
|   |-- pyproject.toml
|   |-- docker-compose.yml         postgres local para desenvolvimento
|   |-- app/                       main, settings, db, models, schemas, security
|   `-- tests/
|-- web/                           index.html, app.js  (config.js e gerado)
|-- scripts/                       up.sh, down.sh, destroy.sh, task-ip.sh
`-- .github/workflows/             validate.yml, deploy.yml
```

## 12. Fases de execução

Cada fase termina com uma verificação observável. Nenhuma fase começa antes da
anterior passar na sua verificação.

| Fase | Entrega | Verificação |
|---|---|---|
| 0 | AWS CLI instalado e configurado; repositório Git e GitHub; stack `00-oidc` | `aws sts get-caller-identity` retorna a conta |
| 1 | Stacks `01-network` e `02-data` | RDS com status `available` via `aws rds describe-db-instances` |
| 2 | API FastAPI, Dockerfile, testes, compose local | `pytest` verde e `curl localhost:8000/auth/login` devolve um JWT |
| 3 | Stack `03-app`; imagem no ECR; task rodando | `curl http://<ip>:8000/health` retorna `{"db":"ok"}` |
| 4 | Stack `04-front`; arquivos no S3 | Cadastro e login funcionam pelo navegador |
| 5 | `validate.yml` e `deploy.yml` | Um push na `main` reconstrói e republica sem intervenção |
| 6 | Stack `05-governance` | E-mail de alarme recebido e evento visível em `aws cloudtrail lookup-events` |

## 13. Riscos

| Risco | Mitigação |
|---|---|
| Conta com mais de 12 meses: RDS deixa de ser free tier | Custo sobe para ~$0,02/h; ciclo efêmero mantém o total em centavos |
| Esquecer a infra ligada | Budget de $5 com alerta em 50%; `make down` no fim de cada sessão |
| IP público da task muda a cada deploy | `config.js` regenerado automaticamente por `up.sh` e pelo pipeline |
| API de login exposta em HTTP na internet | Aceito e documentado: é laboratório, dados descartáveis |
| Deleção de stack falha por bucket não vazio | `destroy.sh` esvazia os buckets antes de remover as stacks |
