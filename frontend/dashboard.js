import { authConfig, getSessionRole, isRole } from "./auth-config.js";

const title = document.querySelector("#dashboard-title");

try {
  const role = authConfig.demoMode
    ? new URLSearchParams(window.location.search).get("role")
    : await getSessionRole();

  if (!isRole(role)) throw new Error("Invalid role.");

  title.textContent = `Trang dashboard của ${role} (chưa thiết kế hoàn chỉnh)`;
} catch {
  window.location.replace("./index.html");
}