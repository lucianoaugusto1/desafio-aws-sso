# Onde a IA se encaixa no ciclo de vida da infraestrutura

Mapa de oportunidades para acelerar provisionamento, deploy e operação usando
agentes de IA.

Não é especulação: cada afirmação aqui foi testada construindo este
repositório do zero — da primeira linha de CloudFormation até o ambiente no ar
e destruído quatro vezes. Onde a experiência contradisse a expectativa, o
documento registra a contradição.

---

## 1. A tese, corrigida

A formulação intuitiva é *"usar IA para criar infra com velocidade"*. Ela está
incompleta, e a diferença importa.

Gerar os 6 templates CloudFormation, os 6 scripts, a API com 29 testes e os 2
workflows levou **horas**. Colocar aquilo no ar levou **quatro tentativas em
dois dias**. Os obstáculos foram:

| Obstáculo | Resolvido gerando mais código? |
|---|---|
| `sub` do GitHub com identificadores imutáveis | Não — resolvido imprimindo as claims do token |
| Falta de permissão `kms:` na role de deploy | Não — resolvido executando com a role escopada |
| Capacidade Fargate indisponível | Não — resolvido esperando |
| AWS CLI do Homebrew quebrada por `libexpat` | Não — resolvido lendo a saída do `otool` |
| Minor do PostgreSQL aposentada | Não — resolvido pelo `cfn-lint` |
| `$VAR:latest` expandido pelo `zsh` | Não — resolvido lendo o erro do push |

**Nenhum foi resolvido gerando código.** Todos foram resolvidos medindo.

A tese corrigida:

> **Gerar rápido + verificar barato + destruir sem medo.** Os três juntos.
> Geração sozinha produz configuração errada com confiança.

---

## 2. A regra do oráculo

Este é o critério que organiza todo o resto.

**O valor da IA numa tarefa é proporcional à qualidade do oráculo disponível** —
o mecanismo rápido, barato e determinístico que diz se o resultado está certo.

| Zona | Existe oráculo? | Postura |
|---|---|---|
| 🟢 **Verde** | Rápido, grátis, determinístico | **Delegue agressivamente.** O agente itera sozinho até passar |
| 🟡 **Amarelo** | Existe, mas é lento ou custa dinheiro | **Agente propõe, humano aprova.** O oráculo é o próprio deploy |
| 🔴 **Vermelho** | Não existe, ou é julgamento | **Agente pesquisa e apresenta; humano decide.** Nunca aceite a conclusão sem a evidência |

Exemplos concretos deste projeto:

- 🟢 `cfn-lint` reprovou `EngineVersion: "16"` em 2 segundos, antes de custar um centavo
- 🟡 O deploy revelou a falta de `kms:` — mas só depois de 8 minutos e alguns centavos
- 🔴 "Qual IdP self-hosted cabe em 512 MB?" — nenhuma ferramenta responde; foi preciso pesquisar e checar relatos de operação reais

**Corolário prático:** antes de delegar uma tarefa de infraestrutura a um
agente, pergunte *"qual é o oráculo?"*. Se não houver, o trabalho do agente é
juntar evidência, não decidir.

---

## 3. Mapa por fase do ciclo de vida

| Fase | Zona | Ganho | O que delegar |
|---|---|---|---|
| Pesquisa e decisão de arquitetura | 🔴 | **Alto** | Levantar opções com números; nunca a escolha final |
| Geração de IaC | 🟢 | **Alto** | Templates, módulos, parametrização |
| Verificação pré-deploy | 🟢 | **Altíssimo** | Lint, testes, política, custo estimado |
| Deploy e CI/CD | 🟡 | Médio | Escrever os workflows; executar sob aprovação |
| Diagnóstico de falha | 🟡 | **Altíssimo** | Correlacionar logs, instrumentar, formular hipótese |
| Custo e FinOps | 🔴 | Médio | Auditar recursos; **nunca** confiar em aritmética de cabeça |
| Segurança e conformidade | 🟡 | Alto | Revisão de código e política; achados precisam de verificação |
| Manutenção e evolução | 🟢 | Médio | Atualizar versões, refatorar, migrar padrões |
| Conhecimento organizacional | 🟢 | **Composto** | Transformar aprendizado em contexto automático |

### 3.1 Pesquisa e decisão de arquitetura 🔴

**Onde encaixa:** levantar alternativas, custos e limitações antes de escrever
qualquer coisa. Três agentes paralelos, neste projeto, produziram em 10 minutos
o que levaria dias de leitura:

- **HTTPS custa US$ 0,00/h** via API Gateway + VPC Link — eu havia afirmado o
  contrário com convicção
- **Dobrar a RAM do Fargate custa +US$ 0,0022/h**, não o dobro — o Fargate
  cobra vCPU e memória separadamente
- **Keycloak sofre OOM em 512 MB** (issue oficial); **Rauthy roda em ~35 MB**

**O padrão que fez diferença:** enquadramento adversarial. Pedir *"seja cético
com números de marketing; prefira relatos reais de operação a documentação
oficial"* trouxe issues do GitHub e CVEs. Uma pergunta neutra teria trazido o
texto dos sites dos fornecedores.

**O limite:** o agente traz evidência, não decisão. Adotar Rauthy, AGPL ou
manter a arquitetura atual é escolha de negócio.

### 3.2 Geração de IaC 🟢

**Onde encaixa:** é o uso óbvio, e funciona — desde que exista lint.

O que **não** é óbvio: a IA gera bem o caminho comum e erra nos defaults
perigosos. Três exemplos deste repositório, todos pegos em revisão:

| Default | Consequência |
|---|---|
| `DeletionPolicy` do RDS é `Snapshot` | O `destroy` deixaria snapshot cobrando |
| Segredo com `Name` fixo | Janela de recuperação de 7 dias impede recriar |
| `MinimumHealthyPercent` padrão 100/200 | Pagaria duas tasks durante cada deploy |

Os três passariam em qualquer lint. **Lint pega sintaxe; revisão pega
intenção.**

### 3.3 Verificação pré-deploy 🟢 — a maior alavanca

Aqui está o ganho mais subestimado. Tudo abaixo roda **sem tocar na nuvem**, em
segundos, de graça:

| Ferramenta | Pega |
|---|---|
| `cfn-lint`, `tflint` | Sintaxe, propriedades inválidas, versões aposentadas |
| `checkov`, `cfn-nag`, `tfsec` | Segurança: `0.0.0.0/0`, bucket público, sem criptografia |
| `conftest` / OPA | Política própria: "toda stack com tag de dono" |
| **Infracost** | **Delta de custo comentado no PR** |
| `pytest`, `bash -n` | Aplicação e scripts |

**Infracost merece destaque.** Eu errei o custo por hora desta stack em 49% —
somei um valor diário como se fosse horário, e repeti o número por várias
mensagens. Um comentário automático no PR com o delta de custo teria exposto
isso na hora. **É a defesa direta contra a aritmética confiante de um LLM.**

### 3.4 Deploy e CI/CD 🟡

**Onde encaixa:** escrever os workflows, o OIDC, os scripts de ciclo de vida.
Poupa horas de boilerplate.

**A descoberta que vale mais que a economia de tempo:** testar como
administrador esconde falhas. O deploy manual funcionou porque eu estava como
usuário raiz. Rodando pelo pipeline, com a role escopada, duas falhas reais
apareceram — o formato do subject claim e a permissão KMS.

> **Uma role de deploy com privilégio mínimo não é só controle de segurança —
> é um teste.** E é o único que pega essa classe de erro.

Dois padrões que se pagaram:

- **Portão de qualidade obrigatório.** Os workflows nasceram independentes: um
  push publicava mesmo com teste quebrado. Hoje o deploy chama a validação como
  workflow reutilizável e depende dela.
- **Gatilho manual em ambiente efêmero.** O deploy automático em cada push
  ressuscitava infraestrutura paga a cada commit — inclusive commits de
  documentação.

### 3.5 Diagnóstico de falha 🟡 — onde a IA mais surpreende

O maior ganho isolado da sessão, e não era o esperado.

O pipeline falhou com `Not authorized to perform sts:AssumeRoleWithWebIdentity`.
Verifiquei role, provider OIDC, audience, nome do repositório — **tudo correto**.
O CloudTrail não registra chamadas STS rejeitadas sem identidade válida. Duas
hipóteses minhas já haviam falhado.

O que resolveu: um workflow descartável imprimindo apenas as claims públicas do
token. O `sub` real era:

```
repo:owner@121799540/repo@1380489339:ref:refs/heads/main
```

O GitHub passou a embutir identificadores numéricos imutáveis. O padrão clássico
`repo:owner/repo:*` jamais casaria.

> **Regra: quando duas hipóteses caem, pare de supor e instrumente.**
> Agentes são bons em gerar hipóteses e péssimos em saber quando parar.

### 3.6 Custo e FinOps 🔴

**Onde encaixa:** auditar o que existe. Depois de cada destruição, uma varredura
por instâncias, snapshots, IPs, buckets e segredos órfãos — algo tedioso que
ninguém faz e que a IA faz sem reclamar. Foi assim que encontramos o snapshot
automático residual que a AWS se recusa a apagar.

**Onde não encaixa:** estimativa. Quatro dos cinco erros que cometi nesta sessão
foram números. Custo é zona vermelha: **peça a fonte, não a conclusão.**

### 3.7 Segurança e conformidade 🟡

Uma auditoria dedicada ao código de autenticação encontrou, entre outros:

- **Negação de serviço trivial** — bcrypt a 239 ms/hash numa task de 0,25 vCPU;
  4 requisições por segundo derrubam a API, e o endpoint de cadastro faz bcrypt
  **sem autenticação**
- **Enumeração de usuários por timing** — `user is None or verify_password(...)`
  faz curto-circuito: 5 ms se o e-mail não existe, 250 ms se existe
- **Segredo que falha aberto** — sem a variável de ambiente do ARN, a aplicação
  sobe assinando tokens com o default público do repositório
- **`max_length=72` conta caracteres, não bytes** — o limite do bcrypt que eu
  documentei não existia, e o teste que o "verificava" testava a coisa errada

Todas verificáveis. Nenhuma óbvia. **E a auditoria contrariou a intuição:** o
que fazia o serviço parecer um brinquedo não era a falta de HTTPS — era a
ausência de revogação, rate limit e registro. Coisas que não dependem de TLS.

### 3.8 Manutenção e evolução 🟢

Atualizar versão, migrar padrão, refatorar. Baixo risco quando há teste.

Um alerta específico: **o conhecimento do modelo envelhece de formas que a
documentação oficial não corrige.** Três casos aqui — o subject claim do GitHub,
a minor do PostgreSQL aposentada, e a fórmula do Homebrew quebrada. Nenhum
aparecia em documentação; todos apareceram executando.

E um quarto, verificado durante a redação deste documento: **o AWS Copilot foi
arquivado em 22 de junho de 2026.** Eu quase o recomendei como a solução "AWS
sem IaC". Um agente com dados de treino de antes dessa data recomendaria uma
ferramenta morta com toda a convicção.

### 3.9 Conhecimento organizacional 🟢 — o de juros compostos

Todo o resto acelera uma vez. Este acelera para sempre.

As 15 armadilhas descobertas neste projeto vivem hoje num arquivo Markdown que
um agente futuro **não vai ler sozinho**. A diferença entre documentação e
comportamento:

| Mecanismo | Efeito |
|---|---|
| `docs/*.md` | Lido se alguém mandar ler |
| **`CLAUDE.md`** | **Carregado em toda sessão, automaticamente** |
| **Skills** | Acionadas quando a tarefa se encaixa |
| **Hooks** | O harness *impõe* — não depende de lembrar |

Um hook `PostToolUse` que roda `cfn-lint` sempre que um template é editado
transforma disciplina em garantia. Um hook `PreToolUse` que exige confirmação em
`delete-stack` transforma cuidado em rede de proteção.

---

## 4. Onde a IA falha de forma previsível

Cinco afirmações minhas nesta sessão, todas plausíveis, todas erradas:

| Afirmei | Real | Erro de |
|---|---|---|
| US$ 0,058/h | US$ 0,039/h | aritmética |
| `max_length=72` impõe o limite do bcrypt | conta caracteres, não bytes | premissa não verificada |
| HTTPS reabre a decisão de custo | custa US$ 0,00/h | não pesquisei |
| Dobrar a RAM dobra o custo | +US$ 0,0022/h | modelo mental errado |
| Metade do código seria aposentada | ~40 linhas | estimativa sem contar |

O padrão: **geração é confiante por construção; a confiança não é sinal de
correção.** Nenhum desses erros foi pego por mim — todos por medição ou por
alguém perguntando.

**Implicação operacional:** trate saída de agente como proposta de colega
competente e apressado. Revisão não é desconfiança; é o mecanismo que faz o
sistema funcionar.

---

## 5. Padrões que funcionaram

1. **Oráculo rápido antes de tudo.** Se não existe lint para o que você está
   gerando, criar um vale mais que gerar mais rápido.
2. **Role de privilégio mínimo como teste**, não só como controle.
3. **Infra efêmera com destruição de um comando.** Torna o erro barato —
   erramos várias vezes por menos de US$ 0,10 no total.
4. **Instrumente quando a segunda hipótese cair.**
5. **Pesquisa adversarial.** Peça ceticismo explícito e fontes primárias.
6. **Auditoria independente após destruir.** Recurso por recurso, sem confiar no
   "custo zero" impresso pelo próprio script.

---

## 6. Ferramentas por camada

| Camada | Opções |
|---|---|
| IaC | CloudFormation, Terraform/OpenTofu, CDK, Pulumi |
| Lint | `cfn-lint`, `tflint` |
| Segurança estática | `checkov`, `cfn-nag`, `tfsec`, Trivy |
| Política | OPA / `conftest` |
| Custo | **Infracost** |
| Dependências | `pip-audit`, Dependabot |
| Postura da conta | Prowler, ScoutSuite |
| Drift | `cloudformation detect-stack-drift`, `driftctl` |
| Contexto para o agente | **AWS MCP servers** (`awslabs/mcp`), Amazon Q Developer CLI |
| Persistência de conhecimento | `CLAUDE.md`, skills, hooks |

**Atenção:** o AWS Copilot aparece em muito material como a resposta para
"AWS sem IaC". Ele foi **arquivado em junho de 2026**.

---

## 7. Roteiro de adoção

Em ordem de retorno sobre esforço:

| # | Ação | Esforço | Retorno |
|---|---|---|---|
| 1 | `CLAUDE.md` com convenções e armadilhas | 1 hora | Muda toda sessão futura |
| 2 | `cfn-lint`/`tflint` no CI | 30 min | Pega erro antes de custar |
| 3 | Repositório-modelo do stack padrão | 1 dia | Projeto novo vira `git clone` |
| 4 | Role de deploy escopada + OIDC | 2 horas | Segurança **e** teste |
| 5 | Infracost no PR | 1 hora | Defesa contra estimativa errada |
| 6 | `checkov` ou `cfn-nag` | 1 hora | Segurança estática |
| 7 | Skill com o runbook | meio dia | Conhecimento vira comportamento |
| 8 | Hooks de lint e confirmação | 2 horas | Disciplina vira garantia |

**Comece pelo 1 e pelo 3.** São os únicos com efeito composto: reduzem o custo
de todo projeto seguinte, não só do atual.

---

## 8. Anti-padrões

- **Aceitar número de agente sem fonte.** Especialmente custo.
- **Deixar o agente aplicar sem diff.** `changeset` e `plan` existem para ser
  lidos.
- **Testar como administrador.** Esconde exatamente a classe de erro que quebra
  em produção.
- **Gerar IaC onde ela não é necessária.** Cinco recursos não justificam
  CloudFormation; um script de CLI resolve. O valor do IaC cresce com a
  quantidade de recursos.
- **Deploy automático em ambiente pago e efêmero.** Um commit de documentação
  não deveria ressuscitar um banco de dados.
- **Documentar em vez de instrumentar.** Markdown que ninguém abre não muda
  comportamento nenhum.

---

## 9. Como saber se está funcionando

| Métrica | Sinal |
|---|---|
| Tempo do primeiro commit ao ambiente no ar | Deve cair de dias para horas |
| Proporção de erros pegos **antes** do deploy | Deve subir |
| Custo de um ciclo completo de erro | Deve ser de centavos |
| Recursos órfãos após destruição | Deve ser zero, e **auditado**, não presumido |
| Armadilhas redescobertas por sessão | Deve cair — se não cai, o conhecimento não virou contexto |

A última é a que mede se a IA está gerando conhecimento acumulado ou apenas
repetindo trabalho com mais velocidade.

---

## Resumo em uma frase

> A IA reduziu a quase zero o custo de **escrever** infraestrutura. Não reduziu
> o custo de **acertá-la**. O ganho real vem de investir o tempo economizado em
> oráculos — lint, política, custo no PR, roles escopadas e ambientes
> descartáveis — e em transformar o que se aprende em contexto automático.
