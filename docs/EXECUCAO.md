# Executando o laboratório, do zero ao custo zero

Roteiro passo a passo. Não é teoria: é o registro de uma execução real feita em
**2026-09-21**, na conta `919995435317`, região `us-east-1`, do provisionamento
até a destruição — com os erros que apareceram no caminho e como cada um foi
resolvido.

**Custo real medido da execução completa: US$ 0,04.**

---

## Antes de começar

| Requisito | Observação |
|---|---|
| Conta AWS | Pessoal, com permissão de administrador |
| Docker | Precisa estar com o daemon rodando para construir a imagem |
| Git e GitHub CLI | `gh auth status` deve responder autenticado |
| Python 3.12+ | Para os testes e o `cfn-lint` |

Todo o laboratório roda por linha de comando. O console da AWS só é necessário
uma vez, para criar o usuário IAM.

---

## Etapa 0 — Ferramentas locais

### 0.1 Instalar a AWS CLI

```bash
curl -fsSL https://awscli.amazonaws.com/v2/install.sh | bash
aws --version
```

Instala em `~/.local/share/aws-cli` com link em `~/.local/bin`, **sem `sudo`**.
Precisa ser **2.32.0 ou maior** para o `aws login` do passo seguinte.

> **Não use `brew install awscli`.** Na execução real isso quebrou:
>
> ```
> aws: [ERROR]: dlopen(.../pyexpat.cpython-314-darwin.so): Symbol not found:
>   _XML_SetAllocTrackerActivationThreshold
> ```
>
> A fórmula do Homebrew usa `python@3.14` compilado com `--with-system-expat`.
> Se o bottle foi construído num macOS mais novo que o seu, o `pyexpat` procura
> um símbolo que a `libexpat` do sistema não exporta — e o `botocore` faz parse
> de XML em toda chamada AWS, então o `aws` morre na partida. O script oficial
> embute o próprio Python e não tem esse acoplamento.

### 0.2 Criar o usuário IAM

No console: **IAM → Users → Create user**, sem acesso ao console. Em
**Attach policies directly**, anexe `AdministratorAccess` e
`SignInLocalDevelopmentAccess`.

Por que admin: o passo 1.1 cria um OIDC provider e uma role IAM com política
inline. Qualquer política que conceda `iam:CreateRole`, `iam:PutRolePolicy` e
`iam:PassRole` já é equivalente a admin — com as três dá para criar uma role
administrativa e assumi-la. Se sua conta for compartilhada e você precisar de
uma política nomeada, use [`infra/policies/usuario-cli.json`](../infra/policies/usuario-cli.json).

### 0.3 Autenticar

```bash
aws configure set region us-east-1
aws login
aws sts get-caller-identity
```

O `aws login` abre o navegador e entrega credenciais **temporárias de até 12
horas** — nenhuma chave de longa duração fica no disco. Ao terminar o dia,
`aws logout`.

Confira o `Arn` da resposta. Se aparecer `:root`, você entrou como usuário
raiz: funciona, mas ignora qualquer política IAM. Prefira um usuário IAM.

### 0.4 Conferir o Docker

```bash
docker info >/dev/null && echo ok
```

Se o daemon estiver parado, no macOS: `open -a Docker`.

---

## Etapa 1 — Bootstrap (uma vez por conta)

Cria a confiança OIDC com o GitHub, a role que o pipeline assume e o
repositório ECR. Custo zero, e **não é removida pelo `make destroy`**.

### 1.1 Criar a stack

```bash
aws cloudformation deploy \
  --stack-name sso-lab-bootstrap \
  --template-file infra/00-bootstrap.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides GitHubOwner=SEU_USUARIO GitHubRepo=desafio-aws-sso
```

Leva menos de um minuto. Confira os outputs:

```bash
aws cloudformation describe-stacks --stack-name sso-lab-bootstrap \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output text
```

```
DeployRoleArn   arn:aws:iam::919995435317:role/sso-lab-bootstrap-deploy
EcrUri          919995435317.dkr.ecr.us-east-1.amazonaws.com/sso-lab-api
```

### 1.2 Entregar os segredos ao GitHub

```bash
ROLE_ARN=$(aws cloudformation describe-stacks --stack-name sso-lab-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text)

gh secret set AWS_DEPLOY_ROLE_ARN --body "$ROLE_ARN"
gh secret set ALERT_EMAIL --body "seu-email@exemplo.com"
```

A partir daqui o pipeline consegue se autenticar sozinho, sem nenhuma chave
armazenada.

### 1.3 Sobre o subject claim do GitHub

A política de confiança da role casa o claim `sub` do token OIDC. O formato que
quase toda documentação mostra é:

```
repo:<dono>/<repo>:ref:refs/heads/<branch>
```

Mas o GitHub passou a emitir **identificadores numéricos imutáveis**:

```
repo:lucianoaugusto1@121799540/desafio-aws-sso@1380489339:ref:refs/heads/main
```

Os números são o id do usuário e o id do repositório. Eles protegem contra
renomear e re-registrar um repositório para herdar a confiança de outro. Por
isso o [`00-bootstrap.yaml`](../infra/00-bootstrap.yaml) aceita os dois padrões,
mantendo os nomes ancorados e deixando só os ids como coringa.

Se o pipeline falhar com `Not authorized to perform sts:AssumeRoleWithWebIdentity`
mesmo com tudo aparentemente correto, inspecione o claim real com um passo
temporário no workflow:

```yaml
- name: claims do token
  run: |
    TOKEN=$(curl -sS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
      "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com" | jq -r .value)
    PAYLOAD=$(echo "$TOKEN" | cut -d. -f2)
    PAD=$(( (4 - ${#PAYLOAD} % 4) % 4 ))
    [ "$PAD" -gt 0 ] && PAYLOAD="${PAYLOAD}$(printf '=%.0s' $(seq 1 $PAD))"
    echo "$PAYLOAD" | tr '_-' '/+' | base64 -d | jq '{iss, aud, sub}'
```

Ele imprime só as claims públicas, nunca o token. O `sub` que aparecer ali é o
que a política precisa casar.

---

## Etapa 2 — Publicar a imagem no ECR

A imagem precisa existir **antes** das stacks: o `03-app` cria um service com
uma task definition que a referencia, e sem imagem a task não inicia.

```bash
ECR=$(aws cloudformation describe-stacks --stack-name sso-lab-bootstrap \
  --query "Stacks[0].Outputs[?OutputKey=='EcrUri'].OutputValue" --output text)
SHA=$(git rev-parse --short HEAD)

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR%%/*}"

docker build --platform linux/amd64 -t "${ECR}:${SHA}" -t "${ECR}:latest" api
docker push "${ECR}:${SHA}"
docker push "${ECR}:latest"
```

Dois detalhes que custaram tempo na execução real:

> **`--platform linux/amd64` não é opcional.** Em Mac com Apple Silicon o
> `docker build` gera `arm64` por padrão, e a task definition declara
> `CpuArchitecture: X86_64`. A task subiria e morreria com `exec format error`.

> **Use chaves na variável: `"${ECR}:latest"`, não `"$ECR:latest"`.** No `zsh`,
> `$VAR:l` é um modificador de expansão que converte para minúsculas. Sem as
> chaves, `$ECR:latest` vira `lowercase($ECR)` + `atest`, e o push falha com
> `The repository with name 'sso-lab-apiatest' does not exist`. A tag com SHA
> escapa por acaso, porque `:7` não é um modificador válido.

---

## Etapa 3 — Subir as cinco stacks

```bash
IMAGE_TAG=$SHA ALERT_EMAIL=seu-email@exemplo.com ./scripts/deploy.sh
```

Ou, com os padrões, `make deploy`.

A ordem é `01-network` → `02-data` → `03-app` → `04-front` → `05-governance`.
**É aqui que a cobrança começa.**

| Stack | Tempo típico |
|---|---|
| `01-network` | ~1 min |
| `02-data` | **8 a 12 min** — o RDS domina |
| `03-app` | ~2 min, esperando a primeira task estabilizar |
| `04-front` | ~30 s |
| `05-governance` | ~1 min |

Acompanhe em outro terminal:

```bash
aws cloudformation describe-stacks \
  --query "Stacks[?starts_with(StackName,'sso-lab')].[StackName,StackStatus]" \
  --output text | sort
```

---

## Etapa 4 — Publicar o front e descobrir o endereço

```bash
make up
```

O `up.sh` escala o service para 1, espera estabilizar, descobre o IP público da
task em três chamadas (`ecs list-tasks` → `ecs describe-tasks` →
`ec2 describe-network-interfaces`), grava esse endereço em `web/config.js` e
sincroniza a pasta `web/` com o bucket.

```
API:  http://34.206.53.184:8000
Site: http://sso-lab-front-919995435317.s3-website-us-east-1.amazonaws.com
```

O IP muda a cada deploy — é por isso que `config.js` não é versionado.

---

## Etapa 5 — Verificar

```bash
API=http://SEU_IP:8000

curl -s $API/health

curl -s -X POST $API/auth/register -H 'content-type: application/json' \
  -d '{"email":"ana@exemplo.com","password":"senha-segura"}'

TOKEN=$(curl -s -X POST $API/auth/login -H 'content-type: application/json' \
  -d '{"email":"ana@exemplo.com","password":"senha-segura"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s $API/auth/me -H "Authorization: Bearer $TOKEN"
```

Resultado da execução real:

| Chamada | Resposta |
|---|---|
| `/health` | `{"status":"ok","db":"ok"}` |
| `/auth/register` | `201` — `{"id":1,"email":"ana@exemplo.com",...}` |
| `/auth/register` repetido | `409` |
| `/auth/login` | JWT |
| `/auth/me` com token | usuário correto |
| `/auth/me` sem token | `401` |

**O `/health` é a verificação que importa.** Se ele responde `{"db":"ok"}`, três
coisas independentes funcionaram: a task tinha permissão IAM para ler o segredo,
o Secrets Manager devolveu a credencial, e o security group deixou a conexão
chegar na porta 5432.

Depois abra o endereço do site no navegador e faça cadastro e login pela
interface — isso também prova que o CORS está correto.

---

## Etapa 6 — Conferir a governança

```bash
# Auditoria: quem fez o quê
aws cloudtrail lookup-events --max-results 5 \
  --query 'Events[].[EventTime,Username,EventName]' --output text

# Logs da aplicação
LG=$(aws cloudformation describe-stacks --stack-name sso-lab-app \
  --query "Stacks[0].Outputs[?OutputKey=='LogGroupName'].OutputValue" --output text)
ST=$(aws logs describe-log-streams --log-group-name "$LG" \
  --order-by LastEventTime --descending --max-items 1 \
  --query 'logStreams[0].logStreamName' --output text)
aws logs get-log-events --log-group-name "$LG" --log-stream-name "$ST" \
  --limit 5 --query 'events[].message' --output text

# Alarmes e orçamento
aws cloudwatch describe-alarms --alarm-name-prefix sso-lab \
  --query 'MetricAlarms[].[AlarmName,StateValue]' --output text
aws budgets describe-budgets --account-id SUA_CONTA \
  --query 'Budgets[].[BudgetName,BudgetLimit.Amount]' --output text
```

> **Confirme a assinatura do SNS.** A AWS envia um e-mail de confirmação e a
> assinatura fica em `PendingConfirmation` até você clicar. Sem isso, nenhum
> alarme chega.

---

## Etapa 7 — Derrubar

Há dois níveis, e a diferença entre eles é a mais importante do laboratório:

```bash
make down      # escala o service para 0
make destroy   # remove as cinco stacks
```

> **`make down` não desliga o RDS.** Ele para o Fargate e libera o IP público,
> mas o banco continua custando **US$ 0,020/h — cerca de US$ 14,80/mês**. Só o
> `make destroy` zera.

Antes do `destroy`, pare o CloudTrail:

```bash
aws cloudtrail stop-logging --name sso-lab-governance-trail
make destroy
```

> **Por quê:** o `destroy.sh` esvazia os buckets e só então remove as stacks. Se
> o CloudTrail continuar gravando nesse intervalo, um objeto novo cai no bucket
> e o CloudFormation recusa apagá-lo, travando a remoção da stack de governança.

---

## Etapa 8 — Auditoria pós-destruição

Não confie no "custo zero" impresso pelo script. Confira você mesmo:

```bash
aws cloudformation describe-stacks \
  --query "Stacks[?starts_with(StackName,'sso-lab')].[StackName,StackStatus]" --output text
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text
aws ecs list-clusters --query 'clusterArns' --output text
aws ec2 describe-network-interfaces \
  --query 'NetworkInterfaces[?Association.PublicIp!=null].[NetworkInterfaceId]' --output text
aws ec2 describe-addresses --query 'Addresses[].PublicIp' --output text
aws ec2 describe-nat-gateways --filter Name=state,Values=available \
  --query 'NatGateways[].NatGatewayId' --output text
aws s3api list-buckets --query "Buckets[?contains(Name,'sso-lab')].Name" --output text
aws secretsmanager list-secrets --include-planned-deletion \
  --query 'SecretList[].[Name,DeletedDate]' --output text
aws budgets describe-budgets --account-id SUA_CONTA --query 'Budgets[].BudgetName' --output text
```

Só a `sso-lab-bootstrap` deve permanecer. Todo o resto vazio.

**Uma sobra esperada:** um snapshot automático do RDS continua listado em
`aws rds describe-db-snapshots --snapshot-type automated`, e a AWS **recusa**
apagá-lo (`InvalidDBSnapshotState: automated snapshots cannot be deleted`). Não
é cobrança: `describe-db-instance-automated-backups` volta vazio, e é esse
recurso que gera custo. Como o `BackupRetentionPeriod` é 1 dia, a entrada some
sozinha. Para evitar até isso, troque `BackupRetentionPeriod: 1` por `0` em
[`infra/02-data.yaml`](../infra/02-data.yaml), desligando backups automáticos.

---

## Armadilhas encontradas nesta execução

| # | Sintoma | Causa | Correção |
|---|---|---|---|
| 1 | `aws` falha com `Symbol not found: _XML_SetAlloc...` | Bottle do `python@3.14` linkado contra `libexpat` mais nova que a do sistema | Instalar pelo script oficial da AWS, não pelo Homebrew |
| 2 | `docker compose up` falha com `port 5432 already allocated` | Outro Postgres ocupando a porta na máquina | O compose publica em **5433**; a API fala com `db:5432` pela rede interna |
| 3 | `cfn-lint` reprova `EngineVersion: "16"` | O major sozinho resolve para uma minor que o RDS não aceita mais | Fixar `16.9`; descobrir versões válidas com `aws rds describe-db-engine-versions` |
| 4 | Push falha com repositório `sso-lab-apiatest` | `$VAR:latest` no `zsh` aplica o modificador `:l` | Usar `"${VAR}:latest"` com chaves |
| 5 | Task morre com `exec format error` | Build em Apple Silicon gera `arm64` | `docker build --platform linux/amd64` |
| 6 | Custo acima do previsto | IPv4 público cobra US$ 0,005/h desde fev/2024 | Inevitável sem load balancer; contabilizar na estimativa |
| 7 | Cobrança de US$ 0,02/dia inesperada | A AWS dá 2 budgets grátis; o do laboratório era o terceiro | Apagar budgets antigos, ou aceitar |
| 8 | Remoção da stack de governança trava | CloudTrail grava no bucket durante o esvaziamento | `aws cloudtrail stop-logging` antes do destroy |
| 9 | Snapshot residual após o destroy | Automático, não removível por design | Some sozinho; ou `BackupRetentionPeriod: 0` |
| 10 | Alarme não chega por e-mail | Assinatura SNS em `PendingConfirmation` | Clicar no link do e-mail de confirmação |
| 11 | CloudTrail registra tudo como `root` | Autenticação feita com o usuário raiz | Criar e usar um usuário IAM |
| 12 | Budget falha com `AccessDenied` | Acesso a faturamento por usuário IAM desativado | Como root: *Account → IAM user and role access to billing information → Activate* |
| 13 | Pipeline falha com `Not authorized to perform sts:AssumeRoleWithWebIdentity`, mesmo com role, provider e `aud` corretos | O `sub` do GitHub traz ids numéricos: `repo:dono@123/repo@456:ref:...`, e o padrão clássico `repo:dono/repo:*` não casa | Aceitar os dois formatos na `StringLike` (veja a seção 1.3) |

---

## Custo real medido

A infraestrutura ficou de pé cerca de 40 minutos.

| Item | Tempo | US$ |
|---|---|---|
| RDS `db.t4g.micro` + 20 GB | ~40 min | 0,013 |
| Fargate 0,25 vCPU + IPv4 público | ~20 min | 0,005 |
| Secrets Manager (2 segredos) | ~40 min | 0,001 |
| Budget (cobrado por dia inteiro) | 1 dia | 0,020 |
| S3, ECR, CloudWatch, CloudTrail | — | 0,000 |
| **Total** | | **≈ 0,04** |

O maior item da conta foi o **budget de alerta**, não a infraestrutura.

Taxas de queima, para referência:

| Estado | US$/h | US$/mês se esquecido |
|---|---|---|
| Tudo ligado | 0,038 | 27,70 |
| `make down` | 0,020 | **14,80** |
| `make destroy` | 0,000 | ~0,01 (imagem no ECR) |

---

## Referência rápida

```bash
make test         # 29 testes da API
make lint         # ruff
make validate     # cfn-lint nos 6 templates
make compose-up   # API + Postgres locais
make deploy       # sobe as cinco stacks
make up           # escala para 1, publica o front, imprime os endereços
make down         # escala para 0
make destroy      # remove tudo (preserva o bootstrap)
```

Depois da Etapa 1, um `git push` na `main` executa as Etapas 2 a 4 sozinho, pelo
[workflow de deploy](../.github/workflows/deploy.yml).
