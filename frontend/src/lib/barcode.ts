/**
 * iOS-first barcode scanning (decision D7): Safari does NOT implement the
 * BarcodeDetector API, so ZXing is the primary engine everywhere; the native
 * detector is only a fast path where it exists (Chromium/Android).
 *
 * The <video> element must already have a live MediaStream attached before
 * calling startBarcodeScan.
 */
import { BrowserMultiFormatReader } from "@zxing/browser";

declare global {
  interface Window {
    BarcodeDetector?: new (options?: { formats?: string[] }) => {
      detect: (source: HTMLVideoElement) => Promise<{ rawValue: string }[]>;
    };
  }
}

export async function startBarcodeScan(
  video: HTMLVideoElement,
  onResult: (barcode: string) => void,
): Promise<() => void> {
  if ("BarcodeDetector" in window && window.BarcodeDetector) {
    const detector = new window.BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"] });
    let stopped = false;
    const loop = async () => {
      if (stopped) return;
      try {
        const codes = await detector.detect(video);
        if (codes.length > 0 && codes[0].rawValue) onResult(codes[0].rawValue);
      } catch {
        /* frame not ready yet */
      }
      if (!stopped) requestAnimationFrame(() => void loop());
    };
    void loop();
    return () => {
      stopped = true;
    };
  }

  const reader = new BrowserMultiFormatReader();
  const controls = await reader.decodeFromVideoElement(video, (result) => {
    if (result) onResult(result.getText());
  });
  return () => controls.stop();
}
