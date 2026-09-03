/**
 * iOS-first barcode scanning (decision D7): Safari does NOT implement the
 * BarcodeDetector API, so ZXing is the primary engine everywhere; the native
 * detector is only a fast path where it exists (Chromium/Android).
 *
 * The <video> element must already have a live MediaStream attached before
 * calling startBarcodeScan.
 */
import { BarcodeFormat, BrowserMultiFormatReader } from "@zxing/browser";
import { DecodeHintType } from "@zxing/library";

const PRODUCT_FORMATS = [BarcodeFormat.EAN_13, BarcodeFormat.EAN_8, BarcodeFormat.UPC_A];

export function isValidProductBarcode(value: string): boolean {
  if (!/^(?:\d{8}|\d{12}|\d{13})$/.test(value)) return false;
  const digits = [...value].map(Number);
  const checkDigit = digits.pop();
  const sum = digits.reverse().reduce(
    (total, digit, index) => total + digit * (index % 2 === 0 ? 3 : 1),
    0,
  );
  return checkDigit === (10 - (sum % 10)) % 10;
}

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
    const detector = new window.BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a"] });
    let stopped = false;
    const loop = async () => {
      if (stopped) return;
      try {
        const codes = await detector.detect(video);
        const productCode = codes.find((code) => isValidProductBarcode(code.rawValue));
        if (productCode) onResult(productCode.rawValue);
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

  const hints = new Map<DecodeHintType, unknown>();
  hints.set(DecodeHintType.POSSIBLE_FORMATS, PRODUCT_FORMATS);
  const reader = new BrowserMultiFormatReader(hints);
  const controls = await reader.decodeFromVideoElement(video, (result) => {
    if (result && isValidProductBarcode(result.getText())) onResult(result.getText());
  });
  return () => controls.stop();
}
