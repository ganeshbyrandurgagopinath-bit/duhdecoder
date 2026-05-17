const clientId = window.DUHDECODER_GOOGLE_CLIENT_ID || "";
const loginStatusEl = document.getElementById("loginStatus");
const buttonContainerEl = document.getElementById("googleButton");

function setStatus(message, isError = false) {
  loginStatusEl.textContent = message;
  loginStatusEl.className = isError ? "login-status error" : "login-status";
}

async function checkSessionAndRedirect() {
  const response = await fetch("/api/auth/session", {
    credentials: "same-origin",
  });

  if (response.ok) {
    window.location.href = "/";
    return true;
  }

  return false;
}

async function handleCredentialResponse(response) {
  setStatus("Signing you in...");

  try {
    const authResponse = await fetch("/api/auth/google", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        credential: response.credential,
      }),
    });

    const payload = await authResponse.json();
    if (!authResponse.ok) {
      throw new Error(payload.error || "Google sign-in failed.");
    }

    const hasSession = await checkSessionAndRedirect();
    if (!hasSession) {
      throw new Error("Sign-in finished, but session was not created.");
    }
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderGoogleButton() {
  if (!clientId || clientId === "__GOOGLE_CLIENT_ID__") {
    setStatus("Google sign-in is not configured yet.", true);
    return;
  }

  if (!window.google?.accounts?.id) {
    setStatus("Loading Google sign-in...");
    window.setTimeout(renderGoogleButton, 500);
    return;
  }

  google.accounts.id.initialize({
    client_id: clientId,
    callback: handleCredentialResponse,
  });

  google.accounts.id.renderButton(buttonContainerEl, {
    theme: "filled_black",
    size: "large",
    type: "standard",
    shape: "pill",
    text: "signin_with",
    width: 280,
  });

  setStatus("Use Google to continue.");
}

window.addEventListener("load", async () => {
  try {
    const hasSession = await checkSessionAndRedirect();
    if (!hasSession) {
      renderGoogleButton();
    }
  } catch {
    renderGoogleButton();
  }
});
