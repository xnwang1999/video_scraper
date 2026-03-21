const $ = (id) => document.getElementById(id);
const API_BASE = () => `http://127.0.0.1:${$("port").value}`;

let currentUrl = "";

document.addEventListener("DOMContentLoaded", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = tab?.url || "";
  $("urlBox").textContent = currentUrl || "无法获取当前页面 URL";

  checkServer();

  $("btnDownload").addEventListener("click", () => sendTask("download"));
  $("btnExtract").addEventListener("click", () => sendTask("extract"));

  $("btnOpen").addEventListener("click", async () => {
    try {
      const resp = await fetch(`${API_BASE()}/api/show`, { signal: AbortSignal.timeout(2000) });
      if (resp.ok) {
        showMsg("已聚焦 GUI 窗口", "success");
        return;
      }
    } catch {}
    // GUI 未运行，尝试通过自定义协议启动
    window.open("videoscraper://open", "_self");
    showMsg("正在启动 GUI...", "");
    // 等待 3 秒后检测是否启动成功
    setTimeout(async () => {
      try {
        const resp = await fetch(`${API_BASE()}/api/health`, { signal: AbortSignal.timeout(2000) });
        if (resp.ok) {
          showMsg("GUI 已启动", "success");
          return;
        }
      } catch {}
      // GUI 未安装，显示下载链接
      showMsg("未检测到 GUI，", "error");
      const link = document.createElement("a");
      link.textContent = "点击此处下载";
      link.href = "#";
      link.style.cssText = "color:#8ab4f8;text-decoration:underline;cursor:pointer";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        chrome.tabs.create({ url: "https://github.com/xnwang1999/video_scraper/releases" });
      });
      $("msg").appendChild(link);
    }, 8000);
  });
});

async function checkServer() {
  try {
    const resp = await fetch(`${API_BASE()}/api/health`, { signal: AbortSignal.timeout(2000) });
    if (resp.ok) {
      $("statusDot").classList.add("connected");
      $("statusDot").title = "桌面端已连接";
    } else {
      throw new Error();
    }
  } catch {
    $("statusDot").classList.add("error");
    $("statusDot").title = "桌面端未启动";
    showMsg("桌面端未启动，请先运行 Video Scraper GUI", "error");
  }
}

const EXTRA_COOKIE_DOMAINS = {
  "youtube.com": [".google.com"],
  "youtu.be": [".google.com"],
};

async function getCookies(url) {
  try {
    const hostname = new URL(url).hostname;
    const parts = hostname.split(".");
    const baseDomain = parts.length > 2 ? parts.slice(-2).join(".") : hostname;

    const fetches = [
      chrome.cookies.getAll({ domain: hostname }),
      hostname !== baseDomain ? chrome.cookies.getAll({ domain: baseDomain }) : Promise.resolve([]),
    ];
    for (const extra of (EXTRA_COOKIE_DOMAINS[baseDomain] || [])) {
      fetches.push(chrome.cookies.getAll({ domain: extra }));
    }

    const results = await Promise.all(fetches);

    const seen = new Set();
    const lines = [];
    for (const c of results.flat()) {
      const key = `${c.domain}|${c.name}|${c.path}`;
      if (seen.has(key)) continue;
      seen.add(key);

      const flag = c.domain.startsWith(".") ? "TRUE" : "FALSE";
      const exp = c.expirationDate ? Math.floor(c.expirationDate) : 0;
      const sec = c.secure ? "TRUE" : "FALSE";
      lines.push(`${c.domain}\t${flag}\t${c.path}\t${sec}\t${exp}\t${c.name}\t${c.value}`);
    }
    return lines.join("\n");
  } catch {
    return "";
  }
}

async function sendTask(action) {
  if (!currentUrl) {
    showMsg("无法获取当前页面 URL", "error");
    return;
  }

  $("btnDownload").disabled = true;
  $("btnExtract").disabled = true;
  showMsg("正在发送...", "");

  try {
    const cookiesText = await getCookies(currentUrl);
    const resp = await fetch(`${API_BASE()}/api/task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentUrl,
        action,
        quality: $("quality").value,
        cookies: cookiesText,
      }),
    });

    const data = await resp.json();
    if (resp.ok) {
      showMsg(data.message || "已发送到桌面端", "success");
    } else {
      showMsg(data.error || "请求失败", "error");
    }
  } catch (e) {
    showMsg("无法连接桌面端，请确认 GUI 已启动", "error");
  } finally {
    $("btnDownload").disabled = false;
    $("btnExtract").disabled = false;
  }
}

function showMsg(text, type) {
  const el = $("msg");
  el.textContent = text;
  el.className = "msg" + (type ? ` ${type}` : "");
}
