// Same-origin connection; never send account/trade data to the decision service.
const frame = document.querySelector("#investment-frame");
const status = document.querySelector("#investment-status");
let pending;
async function connectInvestment(open = false) {
  if (!pending) pending = fetch("./integration/status", { cache: "no-store" })
    .then(async (response) => {
      if (!response.ok) throw new Error("unavailable");
      const info = await response.json();
      if (info.service !== "trading-journal-uat" || !info.ready) throw new Error("unavailable");
      return info;
    }).catch(() => null);
  const info = await pending;
  if (!info) {
    status.textContent = "判定サーバーに接続できません。統合版の start-uat.ps1 を起動して、そのUAT用URLを開いてください。";
    pending = null;
    return;
  }
  document.querySelector("#investment-guest-link").classList.remove("hidden");
  if (!open) return;
  status.textContent = "統合UAT・判定履歴は専用保存。売買記録との関連付けは今後追加します。";
  document.querySelector("#investment-fullscreen").classList.remove("hidden");
  if (!frame.getAttribute("src")) frame.src = "./decision/?embed=true&embedded=1";
  frame.classList.remove("hidden");
}
window.addEventListener("investment:open", () => connectInvestment(true));
connectInvestment();
