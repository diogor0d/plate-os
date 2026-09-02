import { api } from "./api";

const PUSH_OWNER_KEY = "plateos:push-owner-user-id";

export interface PushSubscriptionRecord {
  id: string;
  device_name: string | null;
  created_at: string;
  updated_at: string;
  last_success_at: string | null;
  enabled: boolean;
}

export interface PushStatus {
  enabled: boolean;
  application_server_key: string | null;
  subscriptions: PushSubscriptionRecord[];
}

export function supportsWebPush(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export function applicationServerKey(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const decoded = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(decoded.length));
  for (let index = 0; index < decoded.length; index++) bytes[index] = decoded.charCodeAt(index);
  return bytes;
}

export async function getPushStatus(): Promise<PushStatus> {
  return api<PushStatus>("/api/push");
}

export async function getBrowserSubscription(): Promise<PushSubscription | null> {
  if (!supportsWebPush()) return null;
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

export function getPushOwner(): string | null {
  return localStorage.getItem(PUSH_OWNER_KEY);
}

export async function enableWebPush(publicKey: string, accountId: string): Promise<PushSubscriptionRecord> {
  if (!supportsWebPush()) throw new Error("Web Push is not supported in this browser.");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notification permission was not granted.");
  const registration = await navigator.serviceWorker.ready;
  const current = await registration.pushManager.getSubscription();
  const subscription = current ?? await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: applicationServerKey(publicKey),
  });
  const serialized = subscription.toJSON();
  if (!serialized.endpoint || !serialized.keys?.p256dh || !serialized.keys.auth) {
    if (!current) await subscription.unsubscribe();
    throw new Error("The browser returned an incomplete push subscription.");
  }
  try {
    const saved = await api<PushSubscriptionRecord>("/api/push", {
      method: "PUT",
      body: JSON.stringify({
        endpoint: serialized.endpoint,
        expiration_time: serialized.expirationTime ?? null,
        keys: serialized.keys,
        device_name: "This device",
      }),
    });
    localStorage.setItem(PUSH_OWNER_KEY, accountId);
    return saved;
  } catch (error) {
    if (!current) await subscription.unsubscribe();
    throw error;
  }
}

export async function disableWebPush(): Promise<void> {
  const subscription = await getBrowserSubscription();
  if (!subscription) return;
  await api("/api/push", {
    method: "DELETE",
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  await subscription.unsubscribe();
  localStorage.removeItem(PUSH_OWNER_KEY);
}

export async function revokeWebPushForLogout(accountId: string): Promise<void> {
  if (getPushOwner() !== accountId) return;
  try {
    await disableWebPush();
  } catch {
    const subscription = await getBrowserSubscription();
    await subscription?.unsubscribe();
    localStorage.removeItem(PUSH_OWNER_KEY);
  }
}
