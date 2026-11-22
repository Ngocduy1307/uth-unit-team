import { authConfig, getSessionRole } from "./auth-config.js";

const form = document.querySelector("#login-form");
const employeeId = document.querySelector("#employee-id");
const password = document.querySelector("#password");
const button = document.querySelector("#sign-in");
const error = document.querySelector("#login-error");

document.querySelector("#demo-note").hidden = !authConfig.demoMode;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (button.disabled) return;

  const id = employeeId.value.trim();
  if (!id) {
    error.textContent = "Enter your employee ID.";
    employeeId.focus();
    return;
  }

  const role = new FormData(form).get("role");
  error.textContent = "";

  if (authConfig.demoMode) {
    password.value = "";
    window.location.assign(`./dashboard.html?role=${encodeURIComponent(role)}`);
    return;
  }

  button.disabled = true;
  button.textContent = "Signing in…";

  try {
    const response = await fetch(authConfig.loginEndpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      credentials: "same-origin",
      redirect: "error",
      signal: AbortSignal.timeout(15000),
      body: JSON.stringify({ employeeId: id, password: password.value }),
    });

    if ([400, 401, 403, 422].includes(response.status)) {
      error.textContent = "Check your employee ID and password.";
      return;
    }

    if (response.status === 429) {
      error.textContent = "Too many attempts. Try again later.";
      return;
    }

    if (!response.ok) throw new Error("Login request failed.");

    const sessionRole = await getSessionRole();
    if (sessionRole !== role) {
      error.textContent = "Your account does not have the selected role.";
      return;
    }

    password.value = "";
    window.location.assign("./dashboard.html");
  } catch {
    error.textContent = "Unable to sign in right now. Please try again.";
  } finally {
    button.disabled = false;
    button.textContent = "Sign in";
  }
});

button.disabled = false;