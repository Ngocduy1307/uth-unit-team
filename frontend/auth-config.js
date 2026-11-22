export const authConfig = {
  demoMode: false,
  loginEndpoint: "/api/auth/login",
  sessionEndpoint: "/api/auth/session",
};

export function isRole(value) {
  return ["maker", "checker", "admin"].includes(value);
}

export async function getSessionRole() {
  const response = await fetch(authConfig.sessionEndpoint, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
  });

  if (!response.ok) throw new Error("Session unavailable.");

  const session = await response.json();
  if (session.authenticated !== true || !isRole(session.role)) {
    throw new Error("Invalid session role.");
  }

  return session.role;
}