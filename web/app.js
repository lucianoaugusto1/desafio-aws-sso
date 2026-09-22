"use strict";

const API = (window.API_URL || "").replace(/\/+$/, "");
const CHAVE_TOKEN = "sso-lab.token";
const MAX_ENTRADAS = 20;

const el = (id) => document.getElementById(id);

const ui = {
  pilulaApi: el("pilula-api"),     textoApi: el("texto-api"),
  pilulaBanco: el("pilula-banco"), textoBanco: el("texto-banco"),
  cartaoAcesso: el("cartao-acesso"), cartaoSessao: el("cartao-sessao"),
  abaEntrar: el("aba-entrar"), abaCriar: el("aba-criar"),
  formulario: el("formulario"), enviar: el("enviar"),
  email: el("email"), senha: el("senha"),
  erroEmail: el("erro-email"), erroSenha: el("erro-senha"),
  avisoAcesso: el("aviso-acesso"), avisoSessao: el("aviso-sessao"),
  registro: el("registro"), consoleVazio: el("console-vazio"), console: el("console"),
  rodapeApi: el("rodape-api"),
  btnSair: el("btn-sair"), btnRevalidar: el("btn-revalidar"),
};

let modo = "entrar";       // "entrar" | "criar"
let cronometro = null;

/* ---------------------------------------------------------------- avisos */

function mostrarAviso(nodo, tipo, texto) {
  nodo.dataset.tipo = tipo;
  nodo.textContent = texto;
  nodo.hidden = false;
}

function limparAviso(nodo) {
  nodo.hidden = true;
  nodo.textContent = "";
}

function limparErrosDeCampo() {
  ui.erroEmail.textContent = "";
  ui.erroSenha.textContent = "";
  ui.email.removeAttribute("aria-invalid");
  ui.senha.removeAttribute("aria-invalid");
}

/* --------------------------------------------------------------- console */

function registrar({ metodo, rota, status, ms, corpo, falhou }) {
  ui.consoleVazio.hidden = true;

  const entrada = document.createElement("details");
  entrada.className = "entrada";

  const resumo = document.createElement("summary");
  const selo = document.createElement("span");
  selo.className = "selo";
  selo.dataset.classe = falhou ? "x" : String(status)[0];
  selo.textContent = falhou ? "ERR" : status;

  const alvo = document.createElement("span");
  alvo.textContent = `${metodo} ${rota}`;

  const duracao = document.createElement("span");
  duracao.className = "duracao";
  duracao.textContent = `${ms} ms`;

  resumo.append(selo, alvo, duracao);

  const pre = document.createElement("pre");
  pre.textContent = typeof corpo === "string" ? corpo : JSON.stringify(corpo, null, 2);

  entrada.append(resumo, pre);
  ui.registro.prepend(entrada);

  while (ui.registro.children.length > MAX_ENTRADAS) {
    ui.registro.lastElementChild.remove();
  }
}

/* ------------------------------------------------------------------ http */

async function chamar(rota, opcoes = {}) {
  const metodo = opcoes.method || "GET";
  const inicio = performance.now();

  if (!API) {
    const erro = "window.API_URL não está definido. Falta o config.js.";
    registrar({ metodo, rota, ms: 0, corpo: erro, falhou: true });
    throw new ErroDeRede(erro);
  }

  let resposta;
  try {
    resposta = await fetch(API + rota, opcoes);
  } catch (causa) {
    const ms = Math.round(performance.now() - inicio);
    const erro = `Não foi possível falar com ${API}. A API pode estar fora do ar, ` +
                 `o endereço no config.js pode estar desatualizado, ou o CORS bloqueou.`;
    registrar({ metodo, rota, ms, corpo: `${erro}\n\n${causa}`, falhou: true });
    throw new ErroDeRede(erro);
  }

  const ms = Math.round(performance.now() - inicio);
  const bruto = await resposta.text();
  let corpo;
  try {
    corpo = bruto ? JSON.parse(bruto) : null;
  } catch {
    corpo = bruto;
  }

  registrar({ metodo, rota, status: resposta.status, ms, corpo });
  return { status: resposta.status, ok: resposta.ok, corpo };
}

class ErroDeRede extends Error {}

function json(metodo, dados) {
  return {
    method: metodo,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(dados),
  };
}

function comToken(token) {
  return { headers: { Authorization: `Bearer ${token}` } };
}

/* ------------------------------------------------------------------- jwt */

function decodificarJwt(token) {
  try {
    const parte = token.split(".")[1];
    const base64 = parte.replace(/-/g, "+").replace(/_/g, "/");
    const preenchido = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    return JSON.parse(atob(preenchido));
  } catch {
    return null;
  }
}

const token = {
  ler: () => { try { return localStorage.getItem(CHAVE_TOKEN); } catch { return null; } },
  gravar: (v) => { try { localStorage.setItem(CHAVE_TOKEN, v); } catch { /* modo privado */ } },
  apagar: () => { try { localStorage.removeItem(CHAVE_TOKEN); } catch { /* modo privado */ } },
};

/* ------------------------------------------------------------------ erro */

function traduzirErro(status, corpo) {
  if (status === 401) return "E-mail ou senha incorretos.";
  if (status === 409) return "Este e-mail já está cadastrado. Tente entrar.";
  if (status === 503) return "A API está no ar, mas não alcança o banco de dados.";
  if (status === 422) return null;  // tratado campo a campo
  const detalhe = corpo && typeof corpo.detail === "string" ? corpo.detail : null;
  return detalhe || `Erro inesperado (HTTP ${status}).`;
}

// O Pydantic devolve as mensagens em inglês. Traduzimos as poucas que este
// formulário consegue provocar; o resto passa direto, para nunca ficar mudo.
function traduzirMensagemDeCampo(msg) {
  if (!msg) return "Valor inválido.";
  const minimo = msg.match(/at least (\d+) characters/);
  if (minimo) return `Deve ter pelo menos ${minimo[1]} caracteres.`;
  const maximo = msg.match(/at most (\d+) characters/);
  if (maximo) return `Deve ter no máximo ${maximo[1]} caracteres.`;
  if (/not a valid email address/i.test(msg)) return "E-mail inválido.";
  if (/field required/i.test(msg)) return "Campo obrigatório.";
  if (/should be a valid string/i.test(msg)) return "Deve ser um texto.";
  return msg;
}

function aplicarErrosDeValidacao(corpo) {
  const itens = Array.isArray(corpo?.detail) ? corpo.detail : [];
  let algum = false;
  for (const item of itens) {
    const campo = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
    const alvo = campo === "email" ? ui.erroEmail : campo === "password" ? ui.erroSenha : null;
    const entrada = campo === "email" ? ui.email : campo === "password" ? ui.senha : null;
    if (alvo) {
      alvo.textContent = traduzirMensagemDeCampo(item.msg);
      entrada?.setAttribute("aria-invalid", "true");
      algum = true;
    }
  }
  return algum;
}

/* --------------------------------------------------------------- telas */

function irParaAcesso(aviso) {
  pararCronometro();
  ui.cartaoSessao.hidden = true;
  ui.cartaoAcesso.hidden = false;
  limparAviso(ui.avisoSessao);
  if (aviso) mostrarAviso(ui.avisoAcesso, aviso.tipo, aviso.texto);
}

function irParaSessao(usuario, claims) {
  ui.cartaoAcesso.hidden = true;
  ui.cartaoSessao.hidden = false;
  limparAviso(ui.avisoAcesso);

  el("sessao-email").textContent = usuario.email;
  el("sessao-id").textContent = usuario.id;
  el("sessao-criado").textContent = formatarData(usuario.created_at);
  el("sessao-sub").textContent = claims?.sub ?? "—";
  el("sessao-iat").textContent = claims?.iat ? formatarEpoch(claims.iat) : "—";
  el("sessao-exp").textContent = claims?.exp ? formatarEpoch(claims.exp) : "—";

  iniciarCronometro(claims?.exp);
}

function formatarData(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR");
}

function formatarEpoch(seg) {
  return new Date(seg * 1000).toLocaleString("pt-BR");
}

/* --------------------------------------------------------- cronometro */

function pararCronometro() {
  if (cronometro) { clearInterval(cronometro); cronometro = null; }
}

function iniciarCronometro(exp) {
  pararCronometro();
  const alvo = el("sessao-contagem");
  if (!exp) { alvo.textContent = "—"; return; }

  const tique = () => {
    const restam = Math.floor(exp - Date.now() / 1000);
    if (restam <= 0) {
      alvo.textContent = "expirado";
      pararCronometro();
      token.apagar();
      irParaAcesso({ tipo: "aviso", texto: "Sua sessão expirou. Entre novamente." });
      return;
    }
    const m = String(Math.floor(restam / 60)).padStart(2, "0");
    const s = String(restam % 60).padStart(2, "0");
    alvo.textContent = `${m}:${s}`;
    alvo.dataset.expirando = restam < 60 ? "sim" : "nao";
  };

  tique();
  cronometro = setInterval(tique, 1000);
}

/* ------------------------------------------------------------- saude */

async function verificarSaude() {
  try {
    const { ok, corpo } = await chamar("/health");
    const viva = ok && corpo?.status === "ok";
    ui.pilulaApi.dataset.estado = viva ? "ok" : "erro";
    ui.textoApi.textContent = viva ? "API no ar" : "API com problema";
    const banco = corpo?.db === "ok";
    ui.pilulaBanco.dataset.estado = banco ? "ok" : "erro";
    ui.textoBanco.textContent = banco ? "banco conectado" : "banco inacessível";
  } catch {
    ui.pilulaApi.dataset.estado = "erro";
    ui.textoApi.textContent = "API inalcançável";
    ui.pilulaBanco.dataset.estado = "erro";
    ui.textoBanco.textContent = "banco desconhecido";
  }
}

/* ------------------------------------------------------------- acoes */

async function carregarSessao(jwt, { silencioso = false } = {}) {
  const { status, ok, corpo } = await chamar("/auth/me", comToken(jwt));
  if (ok) {
    irParaSessao(corpo, decodificarJwt(jwt));
    return true;
  }
  token.apagar();
  if (!silencioso) {
    irParaAcesso({ tipo: "aviso", texto: traduzirErro(status, corpo) || "Sessão inválida." });
  } else {
    irParaAcesso();
  }
  return false;
}

async function submeter(evento) {
  evento.preventDefault();
  limparErrosDeCampo();
  limparAviso(ui.avisoAcesso);

  const credenciais = { email: ui.email.value.trim(), password: ui.senha.value };
  const rotulo = ui.enviar.textContent;
  ui.enviar.disabled = true;
  ui.enviar.textContent = modo === "criar" ? "Criando…" : "Entrando…";

  try {
    if (modo === "criar") {
      const r = await chamar("/auth/register", json("POST", credenciais));
      if (!r.ok) return falhaNoFormulario(r);
      mostrarAviso(ui.avisoAcesso, "ok", `Conta criada (id ${r.corpo.id}). Entrando…`);
    }

    const login = await chamar("/auth/login", json("POST", credenciais));
    if (!login.ok) return falhaNoFormulario(login);

    token.gravar(login.corpo.access_token);
    await carregarSessao(login.corpo.access_token);
  } catch (erro) {
    if (erro instanceof ErroDeRede) mostrarAviso(ui.avisoAcesso, "erro", erro.message);
    else throw erro;
  } finally {
    ui.enviar.disabled = false;
    ui.enviar.textContent = rotulo;
  }
}

function falhaNoFormulario({ status, corpo }) {
  if (status === 422 && aplicarErrosDeValidacao(corpo)) {
    mostrarAviso(ui.avisoAcesso, "erro", "Confira os campos destacados.");
    return;
  }
  mostrarAviso(ui.avisoAcesso, "erro", traduzirErro(status, corpo) || "Não foi possível continuar.");
}

function trocarModo(novo) {
  modo = novo;
  const criando = novo === "criar";
  ui.abaCriar.setAttribute("aria-selected", String(criando));
  ui.abaEntrar.setAttribute("aria-selected", String(!criando));
  ui.enviar.textContent = criando ? "Criar conta e entrar" : "Entrar";
  ui.senha.autocomplete = criando ? "new-password" : "current-password";
  limparErrosDeCampo();
  limparAviso(ui.avisoAcesso);
}

/* ------------------------------------------------------------ partida */

ui.abaEntrar.addEventListener("click", () => trocarModo("entrar"));
ui.abaCriar.addEventListener("click", () => trocarModo("criar"));
ui.formulario.addEventListener("submit", submeter);

ui.btnSair.addEventListener("click", () => {
  token.apagar();
  irParaAcesso({ tipo: "ok", texto: "Token removido deste navegador. No servidor ele continua válido até expirar." });
});

ui.btnRevalidar.addEventListener("click", async () => {
  const jwt = token.ler();
  if (!jwt) return irParaAcesso();
  limparAviso(ui.avisoSessao);
  try {
    if (await carregarSessao(jwt)) {
      mostrarAviso(ui.avisoSessao, "ok", "Sessão revalidada contra a API.");
    }
  } catch (erro) {
    if (erro instanceof ErroDeRede) mostrarAviso(ui.avisoSessao, "erro", erro.message);
    else throw erro;
  }
});

(async function iniciar() {
  ui.rodapeApi.textContent = API || "não configurada";
  await verificarSaude();

  const jwt = token.ler();
  if (!jwt) return;

  const claims = decodificarJwt(jwt);
  if (claims?.exp && claims.exp * 1000 <= Date.now()) {
    token.apagar();
    return irParaAcesso({ tipo: "aviso", texto: "Sua sessão anterior expirou." });
  }

  try {
    await carregarSessao(jwt, { silencioso: true });
  } catch { /* a saude ja reportou o problema de rede */ }
})();
