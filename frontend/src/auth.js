// Cognito sign-up / sign-in by calling the Cognito Identity Provider API directly.
// The app client is public (no secret), so these calls need no AWS credentials,
// and no SDK or hosted-UI redirect is needed.

const config = window.INJECTSHIELD_CONFIG || {};
const STORAGE_KEY = "injectshield.session";
const REFRESH_MARGIN_MS = 60_000;

export class AuthError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

async function cognito(action, body) {
  const response = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${action}`,
    },
    body: JSON.stringify({ ClientId: config.userPoolClientId, ...body }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = (data.__type || "Error").split("#").pop();
    throw new AuthError(code, friendly(code, data.message));
  }
  return data;
}

function friendly(code, message) {
  switch (code) {
    case "NotAuthorizedException": return "Incorrect email or password.";
    case "UserNotConfirmedException": return "Please verify your email first.";
    case "UsernameExistsException": return "An account with this email already exists. Sign in instead.";
    case "CodeMismatchException": return "That code is not right. Check the email and try again.";
    case "ExpiredCodeException": return "That code has expired. Send a new one.";
    case "InvalidPasswordException": return "Password needs 8+ characters with upper case, lower case and a number.";
    case "LimitExceededException":
    case "TooManyRequestsException": return "Too many attempts. Wait a minute and try again.";
    default: return message || "Something went wrong talking to Cognito.";
  }
}

function decodeClaims(jwt) {
  const payload = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  const bytes = Uint8Array.from(atob(payload), (c) => c.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

function load() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || null;
  } catch {
    return null;
  }
}

function save(session) {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: the session lives only in memory */
  }
}

let session = load();

function fromResult(result, refreshToken) {
  const claims = decodeClaims(result.IdToken);
  return {
    idToken: result.IdToken,
    refreshToken: result.RefreshToken || refreshToken,
    expiresAt: claims.exp * 1000,
    email: claims.email,
  };
}

export const auth = {
  enabled: !config.authDisabled,

  currentUser() {
    if (!this.enabled) return "local developer";
    return session ? session.email : null;
  },

  async signUp(email, password) {
    await cognito("SignUp", {
      Username: email,
      Password: password,
      UserAttributes: [{ Name: "email", Value: email }],
    });
  },

  async confirm(email, code) {
    await cognito("ConfirmSignUp", { Username: email, ConfirmationCode: code.trim() });
  },

  async resendCode(email) {
    await cognito("ResendConfirmationCode", { Username: email });
  },

  async signIn(email, password) {
    const data = await cognito("InitiateAuth", {
      AuthFlow: "USER_PASSWORD_AUTH",
      AuthParameters: { USERNAME: email, PASSWORD: password },
    });
    if (!data.AuthenticationResult) throw new AuthError(data.ChallengeName, "This account needs an extra sign-in step that the web app does not support.");
    session = fromResult(data.AuthenticationResult);
    save(session);
    return session.email;
  },

  signOut() {
    session = null;
    save(null);
  },

  /** A valid ID token, refreshed when close to expiry; null when signed out. */
  async token() {
    if (!this.enabled) return null;
    if (!session) return null;
    if (Date.now() < session.expiresAt - REFRESH_MARGIN_MS) return session.idToken;
    try {
      const data = await cognito("InitiateAuth", {
        AuthFlow: "REFRESH_TOKEN_AUTH",
        AuthParameters: { REFRESH_TOKEN: session.refreshToken },
      });
      session = fromResult(data.AuthenticationResult, session.refreshToken);
      save(session);
      return session.idToken;
    } catch {
      this.signOut();
      return null;
    }
  },
};
