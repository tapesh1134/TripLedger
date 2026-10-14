export async function api(path, options = {}) {
  const token = sessionStorage.getItem("tripledger-token");
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (response.status === 401) {
    sessionStorage.removeItem("tripledger-token");
    window.dispatchEvent(new Event("session-expired"));
    throw new Error("Session expired or credentials invalid. Please sign in.");
  }
  if (!response.ok) {
    let message = "Request failed. Check services and try again.";
    try {
      const result = await response.json();
      message = result.error || message;
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
export const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
export function downloadJSON(value, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function downloadReceipt(report, id) {
  const response = await fetch(`/api/reports/${report}/receipts/${id}`, {
    headers: {
      Authorization: `Bearer ${sessionStorage.getItem("tripledger-token")}`,
    },
  });
  if (!response.ok) throw new Error("Receipt download failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `receipt-${id}.${blob.type === "image/png" ? "png" : "jpg"}`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
