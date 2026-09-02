self.addEventListener("push", (event) => {
  event.waitUntil(self.registration.showNotification("PlateOS", {
    body: "A planned meal is coming up.",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: "plateos-planned-meal",
    data: { route: "/plan" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (clients) => {
    const existing = clients[0];
    if (existing) {
      if ("navigate" in existing) await existing.navigate("/plan");
      return existing.focus();
    }
    return self.clients.openWindow("/plan");
  }));
});
