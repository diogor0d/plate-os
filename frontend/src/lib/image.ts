/**
 * Client-side media pipeline (brief constraint #3): every image is downscaled
 * on an HTML5 canvas to a max 1280px longest edge and re-encoded at quality
 * 0.7 (WebP with JPEG fallback, ~150KB) BEFORE it touches the network.
 */
export async function downscaleImage(
  file: Blob,
  maxDim = 1280,
  quality = 0.7,
): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();

  const webp = canvas.toDataURL("image/webp", quality);
  if (webp.startsWith("data:image/webp")) return webp;
  return canvas.toDataURL("image/jpeg", quality);
}
