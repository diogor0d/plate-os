/**
 * Scan sheet with camera pipeline redundancy (brief constraint #5):
 * - Barcode: <video> getUserMedia stream fed to ZXing (BarcodeDetector fast
 *   path where available).
 * - Label OCR: native <input type="file" capture="environment"> for maximum
 *   focus quality on small label text, routed through the canvas downscaler
 *   before hitting /api/vision/parse-label.
 * Both paths end in a Proposal Card — nothing is persisted here.
 */
import { useEffect, useRef, useState } from "react";
import { Camera, ScanLine } from "lucide-react";
import { Button } from "./ui/button";
import { api } from "../lib/api";
import { downscaleImage } from "../lib/image";
import { startBarcodeScan } from "../lib/barcode";
import type { FoodItem, Per100 } from "../lib/types";
import { ProposalCard, type ProposalCardItem } from "./ProposalCard";

export function ScanSheet({ onClose }: { onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const stopScanRef = useRef<(() => void) | null>(null);
  const [scanning, setScanning] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ProposalCardItem[] | null>(null);

  useEffect(() => {
    return () => {
      stopScanRef.current?.();
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const stopScan = () => {
    stopScanRef.current?.();
    stopScanRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setScanning(false);
  };

  const startScan = async () => {
    setStatus(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video) return;
      video.srcObject = stream;
      await video.play();
      setScanning(true);
      stopScanRef.current = await startBarcodeScan(video, (barcode) => {
        void handleBarcode(barcode);
      });
    } catch (err) {
      setStatus(`Camera unavailable: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleBarcode = async (barcode: string) => {
    stopScan();
    setStatus(`Looking up ${barcode}…`);
    try {
      const item = await api<FoodItem>(`/api/food-items/barcode/${encodeURIComponent(barcode)}`);
      setProposal([
        {
          name: (item.brand ? `${item.name} (${item.brand})` : item.name).slice(0, 255),
          per100: {
            calories: item.calories_per_100,
            protein_g: item.protein_per_100,
            carbs_g: item.carbs_per_100,
            fat_g: item.fat_per_100,
            fiber_g: item.fiber_per_100,
          },
          quantityG: 100,
          foodItemId: item.id,
          sourceType: "barcode",
        },
      ]);
      setStatus(null);
    } catch (err) {
      setStatus(`Lookup failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleLabelPhoto = async (file: File | undefined) => {
    if (!file) return;
    setStatus("Parsing label…");
    try {
      const dataUrl = await downscaleImage(file);
      const res = await api<{ product_name: string | null; per100: Per100; confidence_score: number }>(
        "/api/vision/parse-label",
        { method: "POST", body: JSON.stringify({ image_base64: dataUrl }) },
      );
      setProposal([
        {
          name: res.product_name ?? "Scanned product",
          per100: res.per100,
          quantityG: 100,
          sourceType: "vision_label",
        },
      ]);
      setStatus(null);
    } catch (err) {
      setStatus(`Label parse failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Scan</h2>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>

      <video
        ref={videoRef}
        className={scanning ? "w-full rounded-xl" : "hidden"}
        playsInline
        muted
      />

      <div className="grid grid-cols-2 gap-3">
        <Button variant="outline" onClick={() => (scanning ? stopScan() : void startScan())}>
          <Camera className="h-4 w-4" />
          {scanning ? "Stop" : "Scan barcode"}
        </Button>
        <label className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-lg border border-zinc-700 text-sm font-medium active:scale-[0.98]">
          <ScanLine className="h-4 w-4" />
          Label photo
          <input
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => void handleLabelPhoto(e.target.files?.[0])}
          />
        </label>
      </div>

      {status && <p className="text-xs text-zinc-400">{status}</p>}

      {proposal && (
        <ProposalCard
          items={proposal}
          onDone={() => {
            setProposal(null);
            onClose();
          }}
        />
      )}
    </div>
  );
}
