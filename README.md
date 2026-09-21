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
| `infra/` | Os 6 templates CloudFormation, de `00-bootstrap` a `05-governance` |
| `infra/policies/` | Política IAM para o usuário que opera o laboratório pela CLI |
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
| 0 | AWS CLI, credenciais, repositório, stack `00-bootstrap` | `aws sts get-caller-identity` |
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

## Fase 0 — preparação da máquina e da conta

Esta é a única fase que não é automatizada: ela cria as credenciais que todo o
resto usa. Rode uma vez.

### 1. Instalar a AWS CLI

Use o script oficial da AWS. Ele instala no seu usuário, sem `sudo`, em
`~/.local/share/aws-cli` com link em `~/.local/bin`:

```bash
curl -fsSL https://awscli.amazonaws.com/v2/install.sh | bash
aws --version
```

> **Não instale pelo Homebrew.** A fórmula `awscli` usa o `python@3.14` do
> Homebrew, que é compilado com `--with-system-expat`. Se o bottle tiver sido
> construído num macOS mais novo que o seu, o `aws` quebra logo na partida com
> `Symbol not found: _XML_SetAllocTrackerActivationThreshold` — o `botocore`
> faz parse de XML em toda chamada. O script oficial embute o próprio Python e
> é imune a isso. Para atualizar depois, use `aws update`.

A CLI precisa ser **2.32.0 ou maior** para o `aws login` do passo 3.

### 2. Criar o usuário IAM

No console: **IAM → Users → Create user**. Não marque acesso ao console — este
usuário é só para a CLI. Em **Set permissions → Attach policies directly**,
anexe **`AdministratorAccess`**.

Vale saber por que admin, e não algo mais restrito: o passo 3 cria um OIDC
provider e uma role IAM com política inline. Qualquer política que permita
`iam:CreateRole`, `iam:PutRolePolicy` e `iam:PassRole` já é equivalente a admin
— com essas três ações dá para criar uma role administrativa e assumi-la.
Restringir aqui custa trabalho sem entregar segurança real.

Se ainda assim precisar de uma política nomeada — conta compartilhada, política
interna —, use [`infra/policies/usuario-cli.json`](infra/policies/usuario-cli.json).
O [README daquela pasta](infra/policies/README.md) explica o alcance dela.

Com o usuário criado: **Security credentials → Create access key → Command line
interface (CLI)**. A *secret access key* aparece uma única vez.

### 3. Autenticar

Prefira o `aws login`: ele autentica pelo navegador com as credenciais que você
já usa no console e entrega credenciais **temporárias**, válidas por até 12
horas. Nenhuma chave de longa duração fica guardada na máquina.

Para usá-lo, anexe ao seu usuário IAM, além do `AdministratorAccess`, a política
gerenciada **`SignInLocalDevelopmentAccess`**. Então:

```bash
aws configure set region us-east-1
aws login
aws sts get-caller-identity
```

Ao terminar a sessão de trabalho, `aws logout`.

**Alternativa com access key.** Se preferir credenciais permanentes, crie uma
access key no usuário IAM (*Security credentials → Create access key → Command
line interface*) e rode `aws configure`, informando chave, segredo, `us-east-1`
e `json`. Funciona igual, mas deixa um segredo de longa duração em
`~/.aws/credentials` — que é justamente o que o resto deste laboratório evita,
já que o pipeline usa OIDC.

### 4. Criar a stack de bootstrap

Ela cria a confiança OIDC com o GitHub, a role de deploy e o repositório ECR.
É a única stack criada à mão, e não é removida pelo `make destroy`.

```bash
aws cloudformation deploy \
  --stack-name sso-lab-bootstrap \
  --template-file infra/00-bootstrap.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides GitHubOwner=lucianoaugusto1 GitHubRepo=desafio-aws-sso
```

### 5. Entregar o ARN da role ao GitHub

```bash
ROLE_ARN=$(aws cloudformation describe-stacks \
  --stack-name sso-lab-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" \
  --output text)

gh secret set AWS_DEPLOY_ROLE_ARN --body "$ROLE_ARN"
gh secret set ALERT_EMAIL --body "seu-email@exemplo.com"
```

A partir daqui, um push na `main` sobe o ambiente inteiro sozinho. Para operar à
mão, use `make deploy`, `make up` e `make down`.

### Duas armadilhas conhecidas

**O AWS Budgets pode recusar mesmo com `AdministratorAccess`.** O acesso a dados
de faturamento por usuário IAM depende de um interruptor separado: logado como
**root**, vá em *Account → IAM user and role access to billing information →
Activate*. Se a stack `sso-lab-governance` falhar com `AccessDenied` em alguma
ação `budgets:`, é quase certo que seja isso.

**A assinatura do SNS precisa ser confirmada.** Depois do primeiro deploy da
stack de governança, a AWS envia um e-mail de confirmação. Sem clicar no link,
nenhum alarme chega.
