const saida = document.getElementById("saida");

function mostrar(titulo, dados) {
  saida.textContent = `${titulo}\n${JSON.stringify(dados, null, 2)}`;
}

function credenciais() {
  return {
    email: document.getElementById("email").value,
    password: document.getElementById("senha").value,
  };
}

async function chamar(rota, opcoes = {}) {
  const resposta = await fetch(`${window.API_URL}${rota}`, opcoes);
  return { status: resposta.status, corpo: await resposta.json() };
}

document.getElementById("btn-cadastrar").onclick = async () => {
  const { status, corpo } = await chamar("/auth/register", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(credenciais()),
  });
  mostrar(`Cadastro — HTTP ${status}`, corpo);
};

document.getElementById("btn-entrar").onclick = async () => {
  const { status, corpo } = await chamar("/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(credenciais()),
  });
  if (corpo.access_token) {
    localStorage.setItem("token", corpo.access_token);
  }
  mostrar(`Login — HTTP ${status}`, corpo);
};

document.getElementById("btn-quem-sou").onclick = async () => {
  const token = localStorage.getItem("token");
  const { status, corpo } = await chamar("/auth/me", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  mostrar(`Sessão — HTTP ${status}`, corpo);
};

document.getElementById("btn-sair").onclick = () => {
  localStorage.removeItem("token");
  saida.textContent = "Token removido do navegador.";
};
