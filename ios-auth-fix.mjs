import { getApps } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js";

const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

const waitForAuth = async () => {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const app = getApps()[0];
    if (app) return getAuth(app);
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("Firebase Auth is not initialized");
};

function installIOSAuthFix() {
  if (!isIOS) return;
  const button = document.querySelector("#login-button");
  const error = document.querySelector("#login-error");
  if (!button) return;

  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    if (error) error.textContent = "";
    button.disabled = true;

    try {
      const auth = await waitForAuth();
      const provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      await signInWithPopup(auth, provider);
    } catch (cause) {
      if (cause?.code === "auth/popup-closed-by-user") return;
      console.error(cause);
      if (error) {
        error.textContent = cause?.code === "auth/popup-blocked"
          ? "Googleログイン画面を開けませんでした。Safariのポップアップブロック設定を確認して、もう一度お試しください。"
          : "ログインできませんでした。もう一度お試しください。";
      }
    } finally {
      button.disabled = false;
    }
  }, { capture: true });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", installIOSAuthFix, { once: true });
} else {
  installIOSAuthFix();
}
