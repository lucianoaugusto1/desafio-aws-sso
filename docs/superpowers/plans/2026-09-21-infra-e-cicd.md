# Plano 2 — Infraestrutura AWS e CI/CD

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colocar a aplicação do Plano 1 no ar na AWS, inteiramente por CloudFormation e AWS CLI, com pipeline de CI/CD, observabilidade, auditoria e teto de gasto.

**Architecture:** Seis templates CloudFormation independentes, ligados por `Outputs` e `Fn::ImportValue`, cada um deployado por um `aws cloudformation deploy` próprio. A task Fargate roda em subnet pública com IP público — sem ALB e sem NAT Gateway, que são os dois maiores custos fixos de uma arquitetura convencional. O endereço da API muda a cada deploy, então o pipeline o descobre e escreve num `config.js` que vai para o S3 junto com o front.

**Tech Stack:** CloudFormation, AWS CLI v2, GitHub Actions com OIDC, cfn-lint, Bash, Make.

**Pré-requisito:** Plano 1 concluído (imagem da API construindo, testes verdes).

**Escopo deste plano:** Seções 4, 5, 8, 9 e 10 do spec — as Fases 0, 1, 3, 4, 5 e 6.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `infra/00-bootstrap.yaml` | Provider OIDC do GitHub, role de deploy, repositório ECR |
| `infra/01-network.yaml` | VPC, 2 subnets públicas, IGW, rotas, 2 security groups |
| `infra/02-data.yaml` | DBSubnetGroup e a instância RDS PostgreSQL |
| `infra/03-app.yaml` | Segredo do JWT, log group, cluster ECS, roles, task definition, service |
| `infra/04-front.yaml` | Bucket S3 com website hosting |
| `infra/05-governance.yaml` | CloudTrail, SNS, metric filter, 2 alarmes, budget |
| `scripts/lib.sh` | Funções compartilhadas: ler output de stack, checar pré-requisitos |
| `scripts/task-ip.sh` | Descobre o IP público da task em execução |
| `scripts/deploy.sh` | Deploy das stacks 01→05 na ordem correta |
| `scripts/up.sh` | Escala para 1, descobre o IP, gera `config.js`, sincroniza o front |
| `scripts/down.sh` | Escala para 0 |
| `scripts/destroy.sh` | Esvazia os buckets e remove as stacks 05→01 |
| `Makefile` | Atalhos: `deploy`, `up`, `down`, `destroy`, `test`, `lint` |
| `.github/workflows/validate.yml` | Lint, testes, cfn-lint e build da imagem |
| `.github/workflows/deploy.yml` | Build, push no ECR, deploy das stacks, publicação do front |

### Por que o ECR fica no `00-bootstrap` e não no `03-app`

Ovo e galinha: o pipeline precisa fazer push da imagem **antes** de criar a task definition que a referencia, mas o repositório ECR precisaria já existir. Separando o ECR para a stack de bootstrap — que é criada uma vez e nunca destruída — a ordem fica sempre: push da imagem, depois deploy das stacks.

### Por que `DesiredCount` tem default 0

Na primeira criação da stack `03-app` a imagem pode ainda não existir. Com `DesiredCount: 0` a stack sobe sem tentar iniciar container nenhum. O pipeline e o `make up` passam `DesiredCount=1` explicitamente.

---

### Task 1: Ferramentas de validação local

**Files:**
- Modify: `api/requirements-dev.txt`

- [ ] **Step 1: Acrescentar o cfn-lint às dependências de desenvolvimento**

Substituir o conteúdo de `api/requirements-dev.txt` por:

```
-r requirements.txt
pytest==8.3.4
httpx==0.28.1
ruff==0.8.6
cfn-lint>=1.20
```

O `cfn-lint` não é dependência da API, mas o venv de desenvolvimento serve como ambiente de ferramentas do laboratório inteiro — manter dois venvs para uma ferramenta só custaria mais confusão do que organiza. A versão vai como faixa, não pino exato, porque o cfn-lint publica correções de regras com frequência e um pino velho reprova templates válidos.

- [ ] **Step 2: Instalar e confirmar**

Run:
```bash
cd api && .venv/bin/pip install -q -r requirements-dev.txt && .venv/bin/cfn-lint --version
```
Expected: imprime a versão, algo como `cfn-lint 1.22.x`

- [ ] **Step 3: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
git add api/requirements-dev.txt
git commit -m "chore(infra): cfn-lint no ambiente de desenvolvimento"
```

---

### Task 2: Stack de bootstrap — OIDC, role de deploy e ECR

**Files:**
- Create: `infra/00-bootstrap.yaml`
- Delete: `infra/.gitkeep`

- [ ] **Step 1: Escrever o template**

`infra/00-bootstrap.yaml`:

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: >
  Bootstrap do laboratorio: confianca OIDC com o GitHub Actions, role de deploy
  e repositorio ECR. Esta stack e criada uma vez e nao e removida pelo destroy.

Parameters:
  GitHubOwner:
    Type: String
    Description: Dono do repositorio no GitHub
    Default: lucianoaugusto1
  GitHubRepo:
    Type: String
    Description: Nome do repositorio no GitHub
    Default: desafio-aws-sso

Resources:
  GitHubOidcProvider:
    Type: AWS::IAM::OIDCProvider
    Properties:
      Url: https://token.actions.githubusercontent.com
      ClientIdList:
        - sts.amazonaws.com
      # A AWS deixou de validar estes thumbprints para o GitHub, mas o recurso
      # ainda exige a propriedade preenchida.
      ThumbprintList:
        - 6938fd4d98bab03faadb97b34396831e3780aea1
        - 1c58a3a8518e8759bf075b76b750d4f2df264fcd

  DeployRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub "${AWS::StackName}-deploy"
      Description: Role assumida pelo GitHub Actions via OIDC
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Federated: !Ref GitHubOidcProvider
            Action: sts:AssumeRoleWithWebIdentity
            Condition:
              StringEquals:
                token.actions.githubusercontent.com:aud: sts.amazonaws.com
              StringLike:
                # Restringe a confianca a este repositorio. Sem esta condicao,
                # qualquer repositorio do GitHub poderia assumir a role.
                token.actions.githubusercontent.com:sub: !Sub "repo:${GitHubOwner}/${GitHubRepo}:*"
      Policies:
        - PolicyName: deploy-do-laboratorio
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              # Amplo dentro dos servicos do laboratorio, e fechado fora deles.
              # Nao e o que se usaria em producao, onde cada acao seria listada.
              - Effect: Allow
                Action:
                  - cloudformation:*
                  - ec2:*
                  - ecr:*
                  - ecs:*
                  - rds:*
                  - s3:*
                  - logs:*
                  - secretsmanager:*
                  - cloudwatch:*
                  - cloudtrail:*
                  - sns:*
                  - budgets:*
                Resource: "*"
              - Effect: Allow
                Action:
                  - iam:CreateRole
                  - iam:DeleteRole
                  - iam:GetRole
                  - iam:PassRole
                  - iam:TagRole
                  - iam:AttachRolePolicy
                  - iam:DetachRolePolicy
                  - iam:PutRolePolicy
                  - iam:DeleteRolePolicy
                  - iam:GetRolePolicy
                  - iam:ListRolePolicies
                  - iam:ListAttachedRolePolicies
                  - iam:CreateServiceLinkedRole
                Resource: "*"

  ApiRepository:
    Type: AWS::ECR::Repository
    Properties:
      RepositoryName: sso-lab-api
      ImageTagMutability: MUTABLE
      ImageScanningConfiguration:
        ScanOnPush: true
      LifecyclePolicy:
        # Sem isto o ECR acumula uma imagem por deploy e sai do free tier.
        LifecyclePolicyText: |
          {
            "rules": [
              {
                "rulePriority": 1,
                "description": "Mantem apenas as 5 imagens mais recentes",
                "selection": {
                  "tagStatus": "any",
                  "countType": "imageCountMoreThan",
                  "countNumber": 5
                },
                "action": { "type": "expire" }
              }
            ]
          }

Outputs:
  DeployRoleArn:
    Description: ARN para o campo role-to-assume do GitHub Actions
    Value: !GetAtt DeployRole.Arn
    Export:
      Name: !Sub "${AWS::StackName}-DeployRoleArn"
  EcrUri:
    Description: URI do repositorio ECR
    Value: !GetAtt ApiRepository.RepositoryUri
    Export:
      Name: !Sub "${AWS::StackName}-EcrUri"
```

- [ ] **Step 2: Validar**

Run: `cd api && .venv/bin/cfn-lint ../infra/00-bootstrap.yaml`
Expected: nenhuma saída (o cfn-lint é silencioso quando aprova)

- [ ] **Step 3: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
rm -f infra/.gitkeep
git add infra/00-bootstrap.yaml
git add -u
git commit -m "feat(infra): stack de bootstrap com OIDC, role de deploy e ECR"
```

---

### Task 3: Stack de rede

**Files:**
- Create: `infra/01-network.yaml`

- [ ] **Step 1: Escrever o template**

`infra/01-network.yaml`:

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: >
  Rede do laboratorio: VPC com duas subnets publicas e dois security groups.
  Sem NAT Gateway - a task Fargate recebe IP publico e alcanca o ECR sozinha.

Parameters:
  VpcCidr:
    Type: String
    Default: 10.0.0.0/16
  ApiPort:
    Type: Number
    Default: 8000
  AllowedCidr:
    Type: String
    Default: 0.0.0.0/0
    Description: Faixa autorizada a chamar a API

Resources:
  Vpc:
    Type: AWS::EC2::VPC
    Properties:
      CidrBlock: !Ref VpcCidr
      EnableDnsSupport: true
      EnableDnsHostnames: true
      Tags:
        - Key: Name
          Value: !Sub "${AWS::StackName}-vpc"

  InternetGateway:
    Type: AWS::EC2::InternetGateway
    Properties:
      Tags:
        - Key: Name
          Value: !Sub "${AWS::StackName}-igw"

  GatewayAttachment:
    Type: AWS::EC2::VPCGatewayAttachment
    Properties:
      VpcId: !Ref Vpc
      InternetGatewayId: !Ref InternetGateway

  PublicSubnetA:
    Type: AWS::EC2::Subnet
    Properties:
      VpcId: !Ref Vpc
      CidrBlock: 10.0.1.0/24
      AvailabilityZone: !Select [0, !GetAZs ""]
      MapPublicIpOnLaunch: true
      Tags:
        - Key: Name
          Value: !Sub "${AWS::StackName}-public-a"

  PublicSubnetB:
    Type: AWS::EC2::Subnet
    Properties:
      VpcId: !Ref Vpc
      CidrBlock: 10.0.2.0/24
      AvailabilityZone: !Select [1, !GetAZs ""]
      MapPublicIpOnLaunch: true
      Tags:
        - Key: Name
          # Existe so porque um DBSubnetGroup exige duas zonas.
          Value: !Sub "${AWS::StackName}-public-b"

  PublicRouteTable:
    Type: AWS::EC2::RouteTable
    Properties:
      VpcId: !Ref Vpc
      Tags:
        - Key: Name
          Value: !Sub "${AWS::StackName}-public"

  DefaultRoute:
    Type: AWS::EC2::Route
    DependsOn: GatewayAttachment
    Properties:
      RouteTableId: !Ref PublicRouteTable
      DestinationCidrBlock: 0.0.0.0/0
      GatewayId: !Ref InternetGateway

  SubnetARouteAssociation:
    Type: AWS::EC2::SubnetRouteTableAssociation
    Properties:
      SubnetId: !Ref PublicSubnetA
      RouteTableId: !Ref PublicRouteTable

  SubnetBRouteAssociation:
    Type: AWS::EC2::SubnetRouteTableAssociation
    Properties:
      SubnetId: !Ref PublicSubnetB
      RouteTableId: !Ref PublicRouteTable

  ApiSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: Entrada HTTP na API
      VpcId: !Ref Vpc
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: !Ref ApiPort
          ToPort: !Ref ApiPort
          CidrIp: !Ref AllowedCidr
          Description: API em HTTP - laboratorio, sem TLS
      Tags:
        - Key: Name
          Value: !Sub "${AWS::StackName}-api"

  DbSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: PostgreSQL acessivel apenas pela API
      VpcId: !Ref Vpc
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 5432
          ToPort: 5432
          SourceSecurityGroupId: !Ref ApiSecurityGroup
          Description: Somente do security group da API
      Tags:
        - Key: Name
          Value: !Sub "${AWS::StackName}-db"

Outputs:
  VpcId:
    Value: !Ref Vpc
    Export:
      Name: !Sub "${AWS::StackName}-VpcId"
  SubnetIds:
    Description: Subnets publicas separadas por virgula
    Value: !Join [",", [!Ref PublicSubnetA, !Ref PublicSubnetB]]
    Export:
      Name: !Sub "${AWS::StackName}-SubnetIds"
  ApiSecurityGroupId:
    Value: !Ref ApiSecurityGroup
    Export:
      Name: !Sub "${AWS::StackName}-ApiSecurityGroupId"
  DbSecurityGroupId:
    Value: !Ref DbSecurityGroup
    Export:
      Name: !Sub "${AWS::StackName}-DbSecurityGroupId"
```

- [ ] **Step 2: Validar**

Run: `cd api && .venv/bin/cfn-lint ../infra/01-network.yaml`
Expected: nenhuma saída

- [ ] **Step 3: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
git add infra/01-network.yaml
git commit -m "feat(infra): VPC, subnets publicas e security groups"
```

---

### Task 4: Stack de dados

**Files:**
- Create: `infra/02-data.yaml`

- [ ] **Step 1: Escrever o template**

`infra/02-data.yaml`:

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: >
  RDS PostgreSQL do laboratorio. Sem IP publico, alcancavel apenas pelo
  security group da API. A senha e gerada e rotacionada pelo proprio RDS
  no Secrets Manager - nenhuma senha aparece neste template.

Parameters:
  NetworkStackName:
    Type: String
    Default: sso-lab-network
    Description: Stack de rede da qual importar VPC e security groups
  DbName:
    Type: String
    Default: sso
  DbInstanceClass:
    Type: String
    Default: db.t4g.micro
    Description: db.t4g.micro esta no free tier por 12 meses
  AllocatedStorage:
    Type: Number
    Default: 20
    Description: 20 GB e o teto do free tier

Resources:
  DbSubnetGroup:
    Type: AWS::RDS::DBSubnetGroup
    Properties:
      DBSubnetGroupDescription: Subnets do laboratorio
      SubnetIds: !Split
        - ","
        - Fn::ImportValue: !Sub "${NetworkStackName}-SubnetIds"

  Database:
    Type: AWS::RDS::DBInstance
    # Por padrao o RDS usa DeletionPolicy Snapshot: o destroy deixaria um
    # snapshot para tras, que continua sendo cobrado. No laboratorio queremos
    # que o destroy realmente zere o custo.
    DeletionPolicy: Delete
    UpdateReplacePolicy: Delete
    Properties:
      DBInstanceIdentifier: !Sub "${AWS::StackName}-postgres"
      Engine: postgres
      EngineVersion: "16"
      DBInstanceClass: !Ref DbInstanceClass
      AllocatedStorage: !Ref AllocatedStorage
      StorageType: gp2
      DBName: !Ref DbName
      MasterUsername: postgres
      ManageMasterUserPassword: true
      DBSubnetGroupName: !Ref DbSubnetGroup
      VPCSecurityGroups:
        - Fn::ImportValue: !Sub "${NetworkStackName}-DbSecurityGroupId"
      PubliclyAccessible: false
      MultiAZ: false
      BackupRetentionPeriod: 1
      DeleteAutomatedBackups: true
      DeletionProtection: false
      AutoMinorVersionUpgrade: true
      Tags:
        - Key: Name
          Value: !Sub "${AWS::StackName}-postgres"

Outputs:
  DbEndpoint:
    Value: !GetAtt Database.Endpoint.Address
    Export:
      Name: !Sub "${AWS::StackName}-DbEndpoint"
  DbPort:
    Value: !GetAtt Database.Endpoint.Port
    Export:
      Name: !Sub "${AWS::StackName}-DbPort"
  DbName:
    Value: !Ref DbName
    Export:
      Name: !Sub "${AWS::StackName}-DbName"
  DbSecretArn:
    Description: Segredo criado e rotacionado pelo proprio RDS
    Value: !GetAtt Database.MasterUserSecret.SecretArn
    Export:
      Name: !Sub "${AWS::StackName}-DbSecretArn"
```

- [ ] **Step 2: Validar**

Run: `cd api && .venv/bin/cfn-lint ../infra/02-data.yaml`
Expected: nenhuma saída

- [ ] **Step 3: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
git add infra/02-data.yaml
git commit -m "feat(infra): RDS PostgreSQL com senha gerenciada no Secrets Manager"
```

---

### Task 5: Stack da aplicação

**Files:**
- Create: `infra/03-app.yaml`

- [ ] **Step 1: Escrever o template**

`infra/03-app.yaml`:

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: >
  Aplicacao no ECS Fargate: segredo do JWT, log group, cluster, roles,
  task definition e service. Sem load balancer - a task recebe IP publico.

Parameters:
  BootstrapStackName:
    Type: String
    Default: sso-lab-bootstrap
  NetworkStackName:
    Type: String
    Default: sso-lab-network
  DataStackName:
    Type: String
    Default: sso-lab-data
  ImageTag:
    Type: String
    Default: latest
  DesiredCount:
    Type: Number
    Default: 0
    Description: >
      Zero por padrao. Na primeira criacao da stack a imagem pode ainda nao
      existir, e task parada nao custa nada. O pipeline passa 1.
  LogRetentionDays:
    Type: Number
    Default: 7
    Description: Retencao curta mantem o uso dentro dos 5 GB gratuitos
  ApiPort:
    Type: Number
    Default: 8000

Resources:
  JwtSecret:
    Type: AWS::SecretsManager::Secret
    Properties:
      # Sem Name de proposito. Um segredo apagado entra numa janela de
      # recuperacao de 7 dias, e recriar outro com o mesmo nome dentro dela
      # falha. Como o laboratorio e destruido e recriado o tempo todo, deixamos
      # o CloudFormation gerar um nome unico e referenciamos pelo ARN.
      Description: Chave de assinatura dos tokens da API
      GenerateSecretString:
        SecretStringTemplate: "{}"
        GenerateStringKey: jwt_secret
        PasswordLength: 48
        ExcludePunctuation: true

  LogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/ecs/${AWS::StackName}"
      RetentionInDays: !Ref LogRetentionDays

  Cluster:
    Type: AWS::ECS::Cluster
    Properties:
      ClusterName: !Sub "${AWS::StackName}-cluster"

  ExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      Description: Usada pelo agente do ECS para puxar a imagem e gravar logs
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Service: ecs-tasks.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

  TaskRole:
    Type: AWS::IAM::Role
    Properties:
      Description: Usada pelo codigo da aplicacao em execucao
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Service: ecs-tasks.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: ler-segredos
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action: secretsmanager:GetSecretValue
                # Restrito aos dois segredos deste laboratorio, nao a todos.
                Resource:
                  - !Ref JwtSecret
                  - Fn::ImportValue: !Sub "${DataStackName}-DbSecretArn"

  TaskDefinition:
    Type: AWS::ECS::TaskDefinition
    Properties:
      Family: !Sub "${AWS::StackName}-api"
      RequiresCompatibilities:
        - FARGATE
      NetworkMode: awsvpc
      Cpu: "256"
      Memory: "512"
      RuntimePlatform:
        OperatingSystemFamily: LINUX
        # Explicito de proposito: build feito em Mac com Apple Silicon gera
        # arm64 por padrao e a task falharia com "exec format error". Os
        # scripts e o pipeline passam --platform linux/amd64.
        CpuArchitecture: X86_64
      ExecutionRoleArn: !GetAtt ExecutionRole.Arn
      TaskRoleArn: !GetAtt TaskRole.Arn
      ContainerDefinitions:
        - Name: api
          Essential: true
          Image: !Sub
            - "${Repo}:${Tag}"
            - Repo:
                Fn::ImportValue: !Sub "${BootstrapStackName}-EcrUri"
              Tag: !Ref ImageTag
          PortMappings:
            - ContainerPort: !Ref ApiPort
              Protocol: tcp
          Environment:
            # ARNs nao sao segredos - sao enderecos. Quem le os segredos e o
            # proprio codigo, com a TaskRole acima.
            - Name: DB_SECRET_ARN
              Value:
                Fn::ImportValue: !Sub "${DataStackName}-DbSecretArn"
            - Name: JWT_SECRET_ARN
              Value: !Ref JwtSecret
            - Name: DB_HOST
              Value:
                Fn::ImportValue: !Sub "${DataStackName}-DbEndpoint"
            - Name: DB_PORT
              Value:
                Fn::ImportValue: !Sub "${DataStackName}-DbPort"
            - Name: DB_NAME
              Value:
                Fn::ImportValue: !Sub "${DataStackName}-DbName"
            - Name: AWS_REGION
              Value: !Ref AWS::Region
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: !Ref LogGroup
              awslogs-region: !Ref AWS::Region
              awslogs-stream-prefix: api

  Service:
    Type: AWS::ECS::Service
    Properties:
      ServiceName: !Sub "${AWS::StackName}-service"
      Cluster: !Ref Cluster
      TaskDefinition: !Ref TaskDefinition
      LaunchType: FARGATE
      PlatformVersion: LATEST
      DesiredCount: !Ref DesiredCount
      DeploymentConfiguration:
        # Sem load balancer e com uma unica task, o padrao (100/200) tentaria
        # subir uma segunda task antes de derrubar a primeira. 0/100 faz o
        # deploy parar e so entao iniciar - alguns segundos de indisponibilidade
        # em troca de nunca pagar duas tasks.
        MinimumHealthyPercent: 0
        MaximumPercent: 100
      NetworkConfiguration:
        AwsvpcConfiguration:
          # Sem NAT Gateway, o IP publico e o que permite puxar do ECR.
          AssignPublicIp: ENABLED
          Subnets: !Split
            - ","
            - Fn::ImportValue: !Sub "${NetworkStackName}-SubnetIds"
          SecurityGroups:
            - Fn::ImportValue: !Sub "${NetworkStackName}-ApiSecurityGroupId"

Outputs:
  ClusterName:
    Value: !Ref Cluster
    Export:
      Name: !Sub "${AWS::StackName}-ClusterName"
  ServiceName:
    Value: !GetAtt Service.Name
    Export:
      Name: !Sub "${AWS::StackName}-ServiceName"
  LogGroupName:
    Value: !Ref LogGroup
    Export:
      Name: !Sub "${AWS::StackName}-LogGroupName"
  JwtSecretArn:
    Value: !Ref JwtSecret
    Export:
      Name: !Sub "${AWS::StackName}-JwtSecretArn"
```

- [ ] **Step 2: Validar**

Run: `cd api && .venv/bin/cfn-lint ../infra/03-app.yaml`
Expected: nenhuma saída

- [ ] **Step 3: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
git add infra/03-app.yaml
git commit -m "feat(infra): cluster ECS, task definition e service Fargate"
```

---

### Task 6: Stack do front

**Files:**
- Create: `infra/04-front.yaml`

- [ ] **Step 1: Escrever o template**

`infra/04-front.yaml`:

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: >
  Bucket S3 servindo o front estatico pelo website endpoint (HTTP puro).
  Sem CloudFront: o front precisa falar com a API em HTTP, e uma pagina
  servida por HTTPS teria a chamada bloqueada por mixed content.

Resources:
  SiteBucket:
    Type: AWS::S3::Bucket
    Properties:
      # Nome de bucket e global na AWS inteira; o id da conta garante unicidade.
      BucketName: !Sub "${AWS::StackName}-${AWS::AccountId}"
      WebsiteConfiguration:
        IndexDocument: index.html
        ErrorDocument: index.html
      PublicAccessBlockConfiguration:
        # Desligado de proposito: sem isto a policy de leitura publica abaixo
        # nao tem efeito e o site responde 403.
        BlockPublicAcls: false
        BlockPublicPolicy: false
        IgnorePublicAcls: false
        RestrictPublicBuckets: false
      OwnershipControls:
        Rules:
          - ObjectOwnership: BucketOwnerEnforced

  SiteBucketPolicy:
    Type: AWS::S3::BucketPolicy
    Properties:
      Bucket: !Ref SiteBucket
      PolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Sid: LeituraPublicaDoSite
            Effect: Allow
            Principal: "*"
            Action: s3:GetObject
            Resource: !Sub "${SiteBucket.Arn}/*"

Outputs:
  BucketName:
    Value: !Ref SiteBucket
    Export:
      Name: !Sub "${AWS::StackName}-BucketName"
  SiteUrl:
    Description: Endereco do site - HTTP, sem TLS
    Value: !GetAtt SiteBucket.WebsiteURL
    Export:
      Name: !Sub "${AWS::StackName}-SiteUrl"
```

- [ ] **Step 2: Validar**

Run: `cd api && .venv/bin/cfn-lint ../infra/04-front.yaml`
Expected: nenhuma saída

- [ ] **Step 3: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
git add infra/04-front.yaml
git commit -m "feat(infra): bucket S3 com website hosting para o front"
```

---

### Task 7: Stack de governança

**Files:**
- Create: `infra/05-governance.yaml`

- [ ] **Step 1: Escrever o template**

`infra/05-governance.yaml`:

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: >
  Governanca do laboratorio: trilha do CloudTrail, alarmes do CloudWatch
  notificando por e-mail e um orcamento mensal com alertas.

Parameters:
  AppStackName:
    Type: String
    Default: sso-lab-app
  AlertEmail:
    Type: String
    Description: E-mail que recebe alarmes e alertas de orcamento
    AllowedPattern: "[^@]+@[^@]+\\.[^@]+"
  MonthlyBudgetUsd:
    Type: Number
    Default: 5

Resources:
  AlertTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: !Sub "${AWS::StackName}-alertas"
      DisplayName: SSO Lab

  AlertSubscription:
    Type: AWS::SNS::Subscription
    Properties:
      TopicArn: !Ref AlertTopic
      Protocol: email
      # A AWS envia um e-mail de confirmacao: sem clicar no link, nenhum
      # alarme chega. Vale conferir a caixa de entrada apos o deploy.
      Endpoint: !Ref AlertEmail

  TrailBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "${AWS::StackName}-trail-${AWS::AccountId}"
      LifecycleConfiguration:
        Rules:
          - Id: expira-em-7-dias
            Status: Enabled
            ExpirationInDays: 7
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true

  TrailBucketPolicy:
    Type: AWS::S3::BucketPolicy
    Properties:
      Bucket: !Ref TrailBucket
      PolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Sid: AWSCloudTrailAclCheck
            Effect: Allow
            Principal:
              Service: cloudtrail.amazonaws.com
            Action: s3:GetBucketAcl
            Resource: !GetAtt TrailBucket.Arn
          - Sid: AWSCloudTrailWrite
            Effect: Allow
            Principal:
              Service: cloudtrail.amazonaws.com
            Action: s3:PutObject
            Resource: !Sub "${TrailBucket.Arn}/AWSLogs/${AWS::AccountId}/*"
            Condition:
              StringEquals:
                s3:x-amz-acl: bucket-owner-full-control

  Trail:
    Type: AWS::CloudTrail::Trail
    # Sem esta dependencia o CloudTrail tenta gravar antes da policy existir
    # e a criacao da stack falha.
    DependsOn: TrailBucketPolicy
    Properties:
      TrailName: !Sub "${AWS::StackName}-trail"
      S3BucketName: !Ref TrailBucket
      IsLogging: true
      IncludeGlobalServiceEvents: true
      # Apenas management events e uma unica regiao: e o que a AWS entrega
      # sem cobrar. Data events (leitura de objeto no S3) seriam pagos.
      IsMultiRegionTrail: false
      EnableLogFileValidation: true

  ApiErrorMetricFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName:
        Fn::ImportValue: !Sub "${AppStackName}-LogGroupName"
      FilterPattern: ERROR
      MetricTransformations:
        - MetricNamespace: SsoLab
          MetricName: ApiErrors
          MetricValue: "1"
          DefaultValue: 0

  ApiErrorAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub "${AWS::StackName}-erros-na-api"
      AlarmDescription: Mais de 5 linhas de ERROR no log em 5 minutos
      Namespace: SsoLab
      MetricName: ApiErrors
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 5
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions:
        - !Ref AlertTopic

  ApiCpuAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub "${AWS::StackName}-cpu-da-task"
      AlarmDescription: CPU da task acima de 80% por 10 minutos
      Namespace: AWS/ECS
      MetricName: CPUUtilization
      Dimensions:
        - Name: ClusterName
          Value:
            Fn::ImportValue: !Sub "${AppStackName}-ClusterName"
        - Name: ServiceName
          Value:
            Fn::ImportValue: !Sub "${AppStackName}-ServiceName"
      Statistic: Average
      Period: 300
      EvaluationPeriods: 2
      Threshold: 80
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions:
        - !Ref AlertTopic

  MonthlyBudget:
    Type: AWS::Budgets::Budget
    Properties:
      Budget:
        BudgetName: !Sub "${AWS::StackName}-mensal"
        BudgetType: COST
        TimeUnit: MONTHLY
        BudgetLimit:
          Amount: !Ref MonthlyBudgetUsd
          Unit: USD
      NotificationsWithSubscribers:
        - Notification:
            NotificationType: ACTUAL
            ComparisonOperator: GREATER_THAN
            Threshold: 50
          Subscribers:
            - SubscriptionType: EMAIL
              Address: !Ref AlertEmail
        - Notification:
            NotificationType: ACTUAL
            ComparisonOperator: GREATER_THAN
            Threshold: 80
          Subscribers:
            - SubscriptionType: EMAIL
              Address: !Ref AlertEmail
        - Notification:
            NotificationType: FORECASTED
            ComparisonOperator: GREATER_THAN
            Threshold: 100
          Subscribers:
            - SubscriptionType: EMAIL
              Address: !Ref AlertEmail

Outputs:
  AlertTopicArn:
    Value: !Ref AlertTopic
  TrailBucketName:
    Value: !Ref TrailBucket
```

- [ ] **Step 2: Validar**

Run: `cd api && .venv/bin/cfn-lint ../infra/05-governance.yaml`
Expected: nenhuma saída

- [ ] **Step 3: Validar os seis templates de uma vez**

Run: `cd api && .venv/bin/cfn-lint ../infra/*.yaml`
Expected: nenhuma saída

- [ ] **Step 4: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
git add infra/05-governance.yaml
git commit -m "feat(infra): CloudTrail, alarmes do CloudWatch e budget mensal"
```

---

### Task 8: Biblioteca compartilhada e descoberta do IP

**Files:**
- Create: `scripts/lib.sh`, `scripts/task-ip.sh`
- Delete: `scripts/.gitkeep`

- [ ] **Step 1: Escrever a biblioteca**

`scripts/lib.sh`:

```bash
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
```

- [ ] **Step 2: Escrever o descobridor de IP**

`scripts/task-ip.sh` — são exatamente os três passos descritos na seção 8 do spec. Não há atalho: sem load balancer, o endereço só existe na interface de rede que o ECS anexou à task.

```bash
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
```

- [ ] **Step 3: Verificar a sintaxe**

Run:
```bash
cd /Users/lucianobr01/desafio-aws-sso
chmod +x scripts/task-ip.sh
bash -n scripts/lib.sh && bash -n scripts/task-ip.sh && echo "sintaxe ok"
```
Expected: imprime `sintaxe ok`

- [ ] **Step 4: Confirmar que falha com mensagem útil sem AWS CLI**

Run: `./scripts/task-ip.sh; echo "codigo de saida: $?"`
Expected: `erro: AWS CLI nao encontrada. Veja a Fase 0 no README.` e `codigo de saida: 1`

- [ ] **Step 5: Commitar**

```bash
cd /Users/lucianobr01/desafio-aws-sso
rm -f scripts/.gitkeep
git add scripts/lib.sh scripts/task-ip.sh
git add -u
git commit -m "feat(scripts): biblioteca compartilhada e descoberta do IP da task"
```

---

### Task 9: Deploy das stacks

**Files:**
- Create: `scripts/deploy.sh`

- [ ] **Step 1: Escrever o script**

`scripts/deploy.sh`:

```bash
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
```

- [ ] **Step 2: Verificar a sintaxe**

Run:
```bash
cd /Users/lucianobr01/desafio-aws-sso
chmod +x scripts/deploy.sh && bash -n scripts/deploy.sh && echo "sintaxe ok"
```
Expected: imprime `sintaxe ok`

- [ ] **Step 3: Commitar**

```bash
git add scripts/deploy.sh
git commit -m "feat(scripts): deploy das cinco stacks na ordem de dependencia"
```

---

### Task 10: Ligar e desligar

**Files:**
- Create: `scripts/up.sh`, `scripts/down.sh`

- [ ] **Step 1: Escrever o `up.sh`**

`scripts/up.sh`:

```bash
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
```

- [ ] **Step 2: Escrever o `down.sh`**

`scripts/down.sh`:

```bash
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
```

- [ ] **Step 3: Verificar a sintaxe**

Run:
```bash
cd /Users/lucianobr01/desafio-aws-sso
chmod +x scripts/up.sh scripts/down.sh
bash -n scripts/up.sh && bash -n scripts/down.sh && echo "sintaxe ok"
```
Expected: imprime `sintaxe ok`

- [ ] **Step 4: Commitar**

```bash
git add scripts/up.sh scripts/down.sh
git commit -m "feat(scripts): ciclo up e down do servico Fargate"
```

---

### Task 11: Destruição

**Files:**
- Create: `scripts/destroy.sh`

- [ ] **Step 1: Escrever o script**

`scripts/destroy.sh` — a ordem é a inversa do deploy, e os buckets precisam ser esvaziados antes: o CloudFormation recusa apagar bucket com objeto dentro.

```bash
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
```

- [ ] **Step 2: Verificar a sintaxe**

Run:
```bash
cd /Users/lucianobr01/desafio-aws-sso
chmod +x scripts/destroy.sh && bash -n scripts/destroy.sh && echo "sintaxe ok"
```
Expected: imprime `sintaxe ok`

- [ ] **Step 3: Commitar**

```bash
git add scripts/destroy.sh
git commit -m "feat(scripts): destruicao das stacks com esvaziamento dos buckets"
```

---

### Task 12: Makefile

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Escrever o Makefile**

`Makefile` — atenção: as linhas de comando precisam começar com **TAB**, não espaços, ou o make recusa o arquivo.

```make
.PHONY: help test lint validate deploy up down destroy compose-up compose-down

help:
	@echo "test         roda os testes da API"
	@echo "lint         roda o ruff na API"
	@echo "validate     roda o cfn-lint nos templates"
	@echo "compose-up   sobe API e Postgres localmente"
	@echo "compose-down derruba o ambiente local"
	@echo "deploy       faz deploy das stacks na AWS"
	@echo "up           escala para 1, descobre o IP e publica o front"
	@echo "down         escala para 0 (para de cobrar Fargate)"
	@echo "destroy      remove todas as stacks do laboratorio"

test:
	cd api && .venv/bin/pytest -q

lint:
	cd api && .venv/bin/ruff check .

validate:
	cd api && .venv/bin/cfn-lint ../infra/*.yaml

compose-up:
	cd api && docker compose up -d --build

compose-down:
	cd api && docker compose down -v

deploy:
	./scripts/deploy.sh

up:
	./scripts/up.sh

down:
	./scripts/down.sh

destroy:
	./scripts/destroy.sh
```

- [ ] **Step 2: Verificar que o make lê o arquivo**

Run: `cd /Users/lucianobr01/desafio-aws-sso && make help`
Expected: imprime as 9 linhas de ajuda, sem erro de separador

- [ ] **Step 3: Verificar os alvos offline**

Run: `cd /Users/lucianobr01/desafio-aws-sso && make lint && make validate && make test`
Expected: ruff sem apontamentos, cfn-lint silencioso, 29 testes passando

- [ ] **Step 4: Commitar**

```bash
git add Makefile
git commit -m "feat: Makefile com os atalhos do laboratorio"
```

---

### Task 13: Workflow de validação

**Files:**
- Create: `.github/workflows/validate.yml`
- Delete: `.github/workflows/.gitkeep`

- [ ] **Step 1: Escrever o workflow**

`.github/workflows/validate.yml`:

```yaml
name: validate

on:
  push:
  pull_request:

jobs:
  api:
    name: testes e lint da API
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: api/requirements-dev.txt
      - run: pip install -r api/requirements-dev.txt
      - name: ruff
        run: ruff check .
        working-directory: api
      - name: pytest
        run: pytest -q
        working-directory: api

  infra:
    name: cfn-lint nos templates
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "cfn-lint>=1.20"
      - run: cfn-lint infra/*.yaml

  image:
    name: build da imagem
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      # --platform linux/amd64 casa com o CpuArchitecture da task definition.
      - run: docker build --platform linux/amd64 -t sso-lab-api:ci api
```

- [ ] **Step 2: Verificar que o YAML é válido**

Run:
```bash
cd /Users/lucianobr01/desafio-aws-sso
api/.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/validate.yml')); print('yaml ok')"
```
Expected: imprime `yaml ok`

- [ ] **Step 3: Commitar**

```bash
rm -f .github/workflows/.gitkeep
git add .github/workflows/validate.yml
git add -u
git commit -m "ci: workflow de validacao com ruff, pytest, cfn-lint e build"
```

---

### Task 14: Workflow de deploy

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Escrever o workflow**

`.github/workflows/deploy.yml`:

```yaml
name: deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

# id-token: write e o que permite ao runner pedir o token OIDC. Sem esta
# permissao o configure-aws-credentials falha sem explicar o motivo.
permissions:
  id-token: write
  contents: read

concurrency:
  group: deploy
  cancel-in-progress: false

env:
  AWS_REGION: us-east-1

jobs:
  deploy:
    name: build, deploy e publicacao
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4

      - name: assumir a role via OIDC
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: login no ECR
        id: ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: build e push da imagem
        env:
          REGISTRY: ${{ steps.ecr.outputs.registry }}
        run: |
          IMAGE="${REGISTRY}/sso-lab-api"
          docker build --platform linux/amd64 \
            -t "${IMAGE}:${GITHUB_SHA}" \
            -t "${IMAGE}:latest" \
            api
          docker push "${IMAGE}:${GITHUB_SHA}"
          docker push "${IMAGE}:latest"

      - name: deploy das stacks
        env:
          IMAGE_TAG: ${{ github.sha }}
          ALERT_EMAIL: ${{ secrets.ALERT_EMAIL }}
        run: ./scripts/deploy.sh

      - name: escalar, descobrir o IP e publicar o front
        run: ./scripts/up.sh

      - name: resumo
        run: |
          {
            echo "### Ambiente publicado"
            echo
            echo '```'
            cat web/config.js
            echo '```'
          } >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Verificar que o YAML é válido**

Run:
```bash
cd /Users/lucianobr01/desafio-aws-sso
api/.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deploy.yml')); print('yaml ok')"
```
Expected: imprime `yaml ok`

- [ ] **Step 3: Commitar**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: workflow de deploy com OIDC, push no ECR e publicacao do front"
```

---

### Task 15: Runbook da Fase 0 no README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Acrescentar a seção ao final do README**

Adicionar ao final de `README.md`:

```markdown
## Fase 0 — preparação da máquina e da conta

Esta é a única fase que não é automatizada: ela cria as credenciais que todo o
resto usa. Rode uma vez.

### 1. Instalar a AWS CLI

```bash
brew install awscli
aws --version
```

### 2. Configurar as credenciais

No console da AWS, em IAM, crie um usuário com `AdministratorAccess` e gere uma
chave de acesso. Então:

```bash
aws configure
```

Informe a chave, o segredo, `us-east-1` como região e `json` como formato.
Confirme:

```bash
aws sts get-caller-identity
```

### 3. Criar a stack de bootstrap

Ela cria a confiança OIDC com o GitHub, a role de deploy e o repositório ECR.
É a única stack criada à mão, e não é removida pelo `make destroy`.

```bash
aws cloudformation deploy \
  --stack-name sso-lab-bootstrap \
  --template-file infra/00-bootstrap.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides GitHubOwner=lucianoaugusto1 GitHubRepo=desafio-aws-sso
```

### 4. Entregar o ARN da role ao GitHub

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

### Confirmar a assinatura do SNS

Depois do primeiro deploy da stack de governança, a AWS envia um e-mail de
confirmação. **Sem clicar no link, nenhum alarme chega.**
```

- [ ] **Step 2: Corrigir o nome da stack na tabela de fases**

O README foi escrito antes de o ECR ser movido para a stack de bootstrap e
ainda cita `00-oidc`. Corrigir a linha da Fase 0:

```bash
cd /Users/lucianobr01/desafio-aws-sso
sed -i "" "s/stack \`00-oidc\`/stack \`00-bootstrap\`/" README.md
grep -n "00-bootstrap" README.md
```

- [ ] **Step 3: Verificar**

Run: `cd /Users/lucianobr01/desafio-aws-sso && grep -c "Fase 0" README.md && grep -c "00-oidc" README.md || true`
Expected: `1` para "Fase 0" (o novo título) e nenhuma ocorrência de `00-oidc`

- [ ] **Step 4: Commitar**

```bash
git add README.md
git commit -m "docs: runbook da Fase 0 com bootstrap e segredos do GitHub"
```

---

## Verificação final do plano

Tudo abaixo roda **sem credencial AWS**:

- [ ] `make validate` → cfn-lint silencioso nos 6 templates
- [ ] `make lint` → ruff sem apontamentos
- [ ] `make test` → 29 testes passando
- [ ] `bash -n` em todos os 6 arquivos de `scripts/` → sem erro de sintaxe
- [ ] `make help` → imprime a ajuda (prova que os TABs do Makefile estão certos)
- [ ] Os dois arquivos de `.github/workflows/` carregam como YAML válido
- [ ] `git log --oneline` → 15 commits, um por task

Com credencial AWS, a sequência da demonstração passa a ser:

| Comando | O que prova |
|---|---|
| `aws cloudformation deploy ... 00-bootstrap.yaml` | Fase 0 |
| `make deploy` | Fases 1, 3, 4 e 6 — as cinco stacks sobem |
| `make up` | A task ganha IP, o front é publicado |
| `curl http://<ip>:8000/health` | A task alcança o RDS lendo o segredo |
| Cadastro e login no navegador | O sistema inteiro funciona ponta a ponta |
| `aws cloudtrail lookup-events --max-results 5` | Fase 6 — auditoria |
| `make down` | O custo de Fargate cessa |
| `make destroy` | O custo vai a zero |
