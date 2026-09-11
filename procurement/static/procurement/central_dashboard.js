(() => {
  const panel = document.getElementById("bid-status");
  const message = document.getElementById("bid-refresh-status");
  if (!panel || !message) return;
  async function refresh() {
    if (!document.hidden) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(panel.dataset.statusUrl, {
          credentials: "same-origin", cache: "no-store", signal: controller.signal
        });
        if (!response.ok) throw new Error("status unavailable");
        const data = await response.json();
        // Do not replace a form while the user is interacting with its buttons.
        if (!panel.contains(document.activeElement)) panel.innerHTML = data.html;
        message.textContent = "상태 갱신: " + new Date().toLocaleTimeString("ko-KR");
      } catch (_) {
        message.textContent = "상태 갱신 실패 · 마지막 표시를 유지합니다. 잠시 후 다시 확인합니다.";
      } finally {
        clearTimeout(timeout);
      }
    }
    setTimeout(refresh, 10000);
  }
  setTimeout(refresh, 10000);
})();
