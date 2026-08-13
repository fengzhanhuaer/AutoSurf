const form = document.querySelector("#login-form");
const username = document.querySelector("#username");
const password = document.querySelector("#password");
const loginButton = document.querySelector("#login-button");
const loginError = document.querySelector("#login-error");

function destination() {
  const candidate = new URLSearchParams(location.search).get("next");
  try {
    const target = new URL(candidate || "/app", location.origin);
    if (target.origin === location.origin && target.pathname !== "/login") {
      return `${target.pathname}${target.search}${target.hash}`;
    }
  } catch (_) {
    // Fall through to the management home page.
  }
  return "/app";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginButton.disabled = true;
  loginButton.textContent = "登录中...";
  loginError.hidden = true;

  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username.value, password: password.value }),
    });
    if (!response.ok) {
      let message = response.status === 401 ? "用户名或密码错误" : `登录失败 (${response.status})`;
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string") message = payload.detail;
      } catch (_) {}
      throw new Error(message);
    }
    location.replace(destination());
  } catch (error) {
    password.value = "";
    loginError.textContent = error.message;
    loginError.hidden = false;
    password.focus();
  } finally {
    loginButton.disabled = false;
    loginButton.textContent = "登录";
  }
});
