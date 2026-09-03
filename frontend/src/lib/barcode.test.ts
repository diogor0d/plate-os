import { afterEach, describe, expect, it, vi } from "vitest";
import { BarcodeFormat } from "@zxing/browser";
import { DecodeHintType } from "@zxing/library";
import { isValidProductBarcode, startBarcodeScan } from "./barcode";

const zxingMock = vi.hoisted(() => ({ hints: null as Map<unknown, unknown> | null }));

vi.mock("@zxing/browser", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@zxing/browser")>();
  return {
    ...actual,
    BrowserMultiFormatReader: class {
      constructor(hints: Map<unknown, unknown>) {
        zxingMock.hints = hints;
      }

      async decodeFromVideoElement(
        _video: HTMLVideoElement,
        callback: (result?: { getText: () => string }) => void,
      ) {
        callback({ getText: () => "50046977" });
        callback({ getText: () => "96385074" });
        return { stop: vi.fn() };
      }
    },
  };
});

afterEach(() => {
  zxingMock.hints = null;
  vi.unstubAllGlobals();
});

describe("product barcode validation", () => {
  it.each(["3017620422003", "5449000000996", "96385074", "036000291452"])(
    "accepts valid GTIN %s",
    (barcode) => expect(isValidProductBarcode(barcode)).toBe(true),
  );

  it.each(["50046977", "3017620422004", "12345678901231", "abc", "123456"])(
    "rejects invalid scan %s",
    (barcode) => expect(isValidProductBarcode(barcode)).toBe(false),
  );

  it("restricts the native detector and uses the first valid result", async () => {
    let requestedFormats: string[] | undefined;
    class FakeBarcodeDetector {
      constructor(options?: { formats?: string[] }) {
        requestedFormats = options?.formats;
      }

      async detect() {
        return [{ rawValue: "50046977" }, { rawValue: "96385074" }];
      }
    }
    vi.stubGlobal("window", { BarcodeDetector: FakeBarcodeDetector });
    vi.stubGlobal("requestAnimationFrame", vi.fn());
    const onResult = vi.fn();

    const stop = await startBarcodeScan({} as HTMLVideoElement, onResult);
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledWith("96385074"));

    expect(requestedFormats).toEqual(["ean_13", "ean_8", "upc_a"]);
    stop();
  });

  it("restricts ZXing formats and filters invalid decoded values", async () => {
    vi.stubGlobal("window", {});
    const onResult = vi.fn();

    const stop = await startBarcodeScan({} as HTMLVideoElement, onResult);

    expect(zxingMock.hints?.get(DecodeHintType.POSSIBLE_FORMATS)).toEqual([
      BarcodeFormat.EAN_13,
      BarcodeFormat.EAN_8,
      BarcodeFormat.UPC_A,
    ]);
    expect(onResult).toHaveBeenCalledOnce();
    expect(onResult).toHaveBeenCalledWith("96385074");
    stop();
  });
});
