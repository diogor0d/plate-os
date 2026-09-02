import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Loader2 } from "lucide-react";
import {
  disableWebPush,
  enableWebPush,
  getBrowserSubscription,
  getPushOwner,
  getPushStatus,
  supportsWebPush,
} from "../lib/push";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

export function PushSettings({ accountId }: { accountId: string }) {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["push-status"], queryFn: getPushStatus });
  const [subscribed, setSubscribed] = useState(false);
  const [ownerMismatch, setOwnerMismatch] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const supported = supportsWebPush();

  useEffect(() => {
    if (!supported) return;
    void getBrowserSubscription().then((value) => {
      setSubscribed(value !== null);
      setOwnerMismatch(value !== null && getPushOwner() !== accountId);
    });
  }, [accountId, supported]);

  const enable = useMutation({
    mutationFn: async () => {
      const key = status.data?.application_server_key;
      if (!key) throw new Error("Web Push is not configured on this PlateOS server.");
      return enableWebPush(key, accountId);
    },
    onSuccess: async () => {
      setSubscribed(true);
      setOwnerMismatch(false);
      setMessage("Meal reminders are enabled on this device.");
      await queryClient.invalidateQueries({ queryKey: ["push-status"] });
    },
    onError: (error) => setMessage(error.message),
  });
  const disable = useMutation({
    mutationFn: disableWebPush,
    onSuccess: async () => {
      setSubscribed(false);
      setOwnerMismatch(false);
      setMessage("Meal reminders are disabled on this device.");
      await queryClient.invalidateQueries({ queryKey: ["push-status"] });
    },
    onError: (error) => setMessage(error.message),
  });
  const busy = enable.isPending || disable.isPending;

  return (
    <Card className="space-y-3">
      <div className="flex items-start gap-3">
        <span className="rounded-lg bg-emerald-500/10 p-2 text-emerald-400">
          {subscribed ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">Meal reminders</h3>
          <p className="mt-1 text-xs leading-relaxed text-zinc-500">
            Notifications use generic lock-screen text and never include meal names or nutrition details.
          </p>
        </div>
      </div>
      {!supported && <p className="text-xs text-amber-400">This browser does not support Web Push. On iPhone, install PlateOS to the Home Screen first.</p>}
      {ownerMismatch && <p className="text-xs text-amber-400">This browser subscription belongs to another PlateOS account. Sign in to that account and log out to revoke it before enabling reminders here.</p>}
      {supported && status.data && !status.data.enabled && <p className="text-xs text-zinc-500">Web Push is not configured by the server operator.</p>}
      {status.error && <p className="text-xs text-red-400">{status.error.message}</p>}
      {message && <p role="status" className={`text-xs ${enable.error || disable.error ? "text-red-400" : "text-emerald-400"}`}>{message}</p>}
      <Button
        size="sm"
        variant={subscribed ? "outline" : "default"}
        disabled={!supported || !status.data?.enabled || busy || ownerMismatch}
        onClick={() => subscribed ? disable.mutate() : enable.mutate()}
      >
        {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {subscribed ? "Disable on this device" : "Enable on this device"}
      </Button>
      {status.data && status.data.subscriptions.length > 0 && (
        <p className="text-[11px] text-zinc-600">
          {status.data.subscriptions.filter((item) => item.enabled).length} active household device subscription(s) for this account.
        </p>
      )}
    </Card>
  );
}
