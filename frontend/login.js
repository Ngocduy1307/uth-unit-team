import { authConfig } from "./auth-config.js";

const form = document.querySelector("#login-form");
const employeeId = document.querySelector("#employee-id");
const password = document.querySelector("#password");
const button = document.querySelector("#sign-in");
const error = document.querySelector("#login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (button.disabled) return;

  const id = employeeId.value.trim();
  if (!id) {
    error.textContent = "Enter your employee ID.";
    employeeId.focus();
    return;
  }

  error.textContent = "";
  button.disabled = true;
  button.textContent = "Signing in…";

  try {
    const login = await fetch(authConfig.loginEndpoint, {
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

    if ([400, 401, 403, 422].includes(login.status)) {
      error.textContent = "Check your employee ID and password.";
      return;
    }

    if (login.status === 429) {
      error.textContent = "Too many attempts. Try again later.";
      return;
    }

    if (!login.ok) throw new Error("Login request failed.");

    const session = await fetch(authConfig.sessionEndpoint, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(15000),
    });

    if (!session.ok || (await session.json()).authenticated !== true) {
      throw new Error("Session could not be verified.");
    }

    password.value = "";
    window.location.assign(authConfig.afterSignIn);
  } catch {
    error.textContent = "Unable to sign in right now. Please try again.";
  } finally {
    button.disabled = false;
    button.textContent = "Sign in";
  }
});

button.disabled = false;