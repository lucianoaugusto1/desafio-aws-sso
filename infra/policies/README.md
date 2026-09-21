# Políticas IAM

## `usuario-cli.json`

Política para o **usuário IAM que você opera da sua máquina** — o que roda
`aws configure`, cria a stack de bootstrap e, se quiser, executa `make deploy`,
`make up` e `make destroy` localmente.

### Quando usar

Só se a conta for compartilhada ou tiver alguma exigência de restrição.

**Em conta pessoal, use `AdministratorAccess`.** Esta política permite
`iam:CreateRole`, `iam:PutRolePolicy` e `iam:PassRole` — quem tem essas três
ações consegue criar uma role com `AdministratorAccess` e assumi-la. Ou seja,
ela não é realmente menos privilegiada que admin; apenas parece. O ganho real
é de organização e de deixar registrado o que o laboratório toca.

### Como aplicar

```bash
aws iam put-user-policy \
  --user-name sso-lab-cli \
  --policy-name sso-lab-cli \
  --policy-document file://infra/policies/usuario-cli.json
```

Ou, no console: **IAM → Users → (usuário) → Add permissions → Create inline
policy → JSON**, colando o conteúdo do arquivo.

### Relação com a role de deploy

Os `Statement` `CloudFormation` e `ServicosDoLaboratorio` são os mesmos da role
que o GitHub Actions assume, definida em `../00-bootstrap.yaml`. A diferença
está no `IamParaOBootstrap`: o seu usuário precisa criar o **OIDC provider**, e
a role de deploy não — ele é criado uma única vez, por você, na Fase 0.

Se você alterar a lista de serviços em um dos dois lugares, altere no outro.
