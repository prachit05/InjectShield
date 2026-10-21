// Local development defaults (docker compose, AUTH_DISABLED=true).
// scripts/deploy.sh uploads a generated config.js in its place on AWS.
window.INJECTSHIELD_CONFIG = {
  apiBase: "http://localhost:8000",
  authDisabled: true,
  region: "",
  userPoolClientId: "",
};
