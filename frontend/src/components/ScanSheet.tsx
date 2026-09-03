import { useEffect, useRef, useState } from "react";
import { Camera, CheckCircle2, Library, ScanLine, ShieldCheck, TriangleAlert } from "lucide-react";
import { Button } from "./ui/button";
import { ApiError, api } from "../lib/api";
import { downscaleImage } from "../lib/image";
import { startBarcodeScan } from "../lib/barcode";
import { ProposalCard, type ProposalCardItem } from "./ProposalCard";
import { ProductFields, ProductLibrary } from "./ProductLibrary";
import {
  candidateDraftIsUnchanged,
  bindCandidateBarcode,
  createProduct,
  draftFromCandidate,
  draftWithBoundCandidateBarcode,
  per100FromProduct,
  productFingerprint,
  sourceLabel,
  stableMutation,
  validateProductDraft,
  type BarcodeResolution,
  type Product,
  type ProductCandidate,
  type ProductDraft,
  type StableMutation,
} from "../lib/products";

export function ScanSheet({ onClose }: { onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const stopScanRef = useRef<(() => void) | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanPurpose, setScanPurpose] = useState<"lookup" | "attach" | null>(null);
  const [scanStarting, setScanStarting] = useState(false);
  const [bindingBarcode, setBindingBarcode] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ProposalCardItem[] | null>(null);
  const [candidate, setCandidate] = useState<ProductCandidate | null>(null);
  const [draft, setDraft] = useState<ProductDraft | null>(null);
  const [comparison, setComparison] = useState<ProductCandidate | null>(null);
  const [notFound, setNotFound] = useState<string | null>(null);
  const [proposalProvenance, setProposalProvenance] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saveMutation = useRef<StableMutation | null>(null);
  const candidateRef = useRef<ProductCandidate | null>(null);
  const draftRef = useRef<ProductDraft | null>(null);
  const mountedRef = useRef(false);
  const startingScanRef = useRef(false);
  const scanAttemptRef = useRef(0);
  candidateRef.current = candidate;
  draftRef.current = draft;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      scanAttemptRef.current += 1;
      stopScanRef.current?.();
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const stopScan = () => {
    scanAttemptRef.current += 1;
    startingScanRef.current = false;
    setScanStarting(false);
    stopScanRef.current?.();
    stopScanRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setScanning(false);
    setScanPurpose(null);
  };

  const startScan = async (purpose: "lookup" | "attach" = "lookup") => {
    if (startingScanRef.current || bindingBarcode || saving) return;
    startingScanRef.current = true;
    setScanStarting(true);
    const scanAttempt = ++scanAttemptRef.current;
    let stream: MediaStream | null = null;
    if (purpose === "lookup") {
      setCandidate(null);
      setDraft(null);
      setComparison(null);
      setNotFound(null);
      setProposal(null);
      setProposalProvenance(null);
    }
    setError(null);
    setStatus(purpose === "attach" ? "Point the camera at this product's barcode." : null);
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      if (!mountedRef.current || scanAttemptRef.current !== scanAttempt) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video) {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        return;
      }
      video.srcObject = stream;
      await video.play();
      if (!mountedRef.current || scanAttemptRef.current !== scanAttempt) {
        stream.getTracks().forEach((track) => track.stop());
        if (streamRef.current === stream) streamRef.current = null;
        return;
      }
      setScanning(true);
      setScanPurpose(purpose);
      const stopDecoder = await startBarcodeScan(video, (barcode) => {
        void handleBarcode(barcode, purpose);
      });
      if (!mountedRef.current || scanAttemptRef.current !== scanAttempt) {
        stopDecoder();
        stream.getTracks().forEach((track) => track.stop());
        if (streamRef.current === stream) streamRef.current = null;
        return;
      }
      stopScanRef.current = stopDecoder;
    } catch (err) {
      stream?.getTracks().forEach((track) => track.stop());
      if (streamRef.current === stream) streamRef.current = null;
      if (mountedRef.current && scanAttemptRef.current === scanAttempt) {
        setScanning(false);
        setScanPurpose(null);
        setStatus(`Camera unavailable: ${err instanceof Error ? err.message : String(err)}`);
      }
    } finally {
      if (scanAttemptRef.current === scanAttempt) {
        startingScanRef.current = false;
        setScanStarting(false);
      }
    }
  };

  const handleBarcode = async (barcode: string, purpose: "lookup" | "attach") => {
    stopScan();
    if (purpose === "attach") {
      const currentCandidate = candidateRef.current;
      const currentDraft = draftRef.current;
      if (!currentCandidate || !currentDraft) return;
      setBindingBarcode(true);
      setError(null);
      setStatus(`Adding barcode ${barcode}...`);
      try {
        const rebound = await bindCandidateBarcode(currentCandidate, barcode);
        if (!mountedRef.current || candidateRef.current !== currentCandidate || draftRef.current !== currentDraft) return;
        setCandidate(rebound);
        setDraft(draftWithBoundCandidateBarcode(currentDraft, rebound));
        setStatus(`Barcode ${barcode} added to this label candidate.`);
      } catch (err) {
        if (!mountedRef.current || candidateRef.current !== currentCandidate || draftRef.current !== currentDraft) return;
        setStatus(null);
        setError(`Barcode could not be added: ${err instanceof Error ? err.message : String(err)}`);
      } finally {
        if (mountedRef.current) setBindingBarcode(false);
      }
      return;
    }
    setCandidate(null);
    setDraft(null);
    setComparison(null);
    setNotFound(null);
    setProposal(null);
    setProposalProvenance(null);
    setError(null);
    setStatus(`Looking up ${barcode}...`);
    try {
      const resolution = await api<BarcodeResolution>(`/api/food-items/barcode/${encodeURIComponent(barcode)}`);
      if (resolution.kind === "accepted") {
        setProposal([proposalFromProduct(resolution.product)]);
        setProposalProvenance(`Accepted local product · ${sourceLabel(resolution.product.nutrition_source)}`);
      } else if (resolution.kind === "candidate") {
        setCandidate(resolution.candidate);
        setDraft(draftFromCandidate(resolution.candidate));
      } else {
        setNotFound(resolution.barcode);
      }
      setStatus(null);
    } catch (err) {
      setStatus(null);
      if (err instanceof ApiError && err.status === 502) {
        setError("Open Food Facts could not be reached. This is an upstream error, not a confirmed barcode miss. Try again later or use a label photo.");
      } else {
        setError(`Lookup failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  };

  const parseLabel = async (file: File | undefined, compare: boolean) => {
    if (!file) return;
    setError(null);
    setStatus(compare ? "Comparing label..." : "Parsing label...");
    try {
      const dataUrl = await downscaleImage(file);
      const barcode = draft?.barcode.trim();
      const query = barcode ? `?barcode=${encodeURIComponent(barcode)}` : "";
      const result = await api<ProductCandidate>(
        `/api/vision/parse-label${query}`,
        { method: "POST", body: JSON.stringify({ image_base64: dataUrl }) },
      );
      if (compare && candidate) {
        setComparison(result);
      } else {
        setCandidate(result);
        setDraft(draftFromCandidate(result));
        setComparison(null);
        setNotFound(null);
        setProposal(null);
        setProposalProvenance(null);
      }
      setStatus(null);
    } catch (err) {
      setStatus(null);
      const detail = (err instanceof Error ? err.message : String(err)).trim();
      setError(
        `Label scanning unavailable: ${detail || "The photo could not be processed. Try another image or test the label scanning provider in Settings."}`,
      );
    }
  };

  const reviewValue = () => {
    if (!draft) return null;
    const validated = validateProductDraft(draft);
    if (validated.error) {
      setError(validated.error);
      return null;
    }
    return validated.value;
  };

  const logOnce = () => {
    if (bindingBarcode || scanning || startingScanRef.current) return;
    const value = reviewValue();
    if (!value) return;
    setError(null);
    const sourceType = value.nutrition_source === "vision_label"
      ? "vision_label"
      : value.nutrition_source === "open_food_facts" ? "barcode" : "manual";
    setProposal([{
      name: value.brand ? `${value.name} (${value.brand})`.slice(0, 255) : value.name,
      per100: value.per100,
      sourceType,
      quantityG: candidate?.suggested_quantity_g ?? 100,
      quantityUnit: value.serving_unit.toLowerCase() === "ml" ? "ml" : "g",
    }]);
    setProposalProvenance(
      `${sourceLabel(value.nutrition_source)} · one-time log, not saved to your library`,
    );
  };

  const save = async (andLog: boolean) => {
    if (bindingBarcode || scanning || startingScanRef.current) return;
    const value = reviewValue();
    if (!value) return;
    const fingerprint = productFingerprint({ operation: "create", value });
    saveMutation.current = stableMutation(saveMutation.current, fingerprint);
    setSaving(true);
    setError(null);
    try {
      const suggestedQuantityG = candidate?.suggested_quantity_g ?? 100;
      const product = await createProduct(value, saveMutation.current.id);
      saveMutation.current = null;
      setCandidate(null);
      setDraft(null);
      setComparison(null);
      if (andLog) {
        const sourceType = product.nutrition_source === "vision_label"
          ? "vision_label"
          : product.nutrition_source === "open_food_facts" ? "barcode" : "manual";
        setProposal([proposalFromProduct(product, suggestedQuantityG, sourceType)]);
        setProposalProvenance(`Accepted local product · ${sourceLabel(product.nutrition_source)}`);
      } else {
        setStatus(`${product.name} is now an accepted product.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const useComparison = () => {
    if (!comparison || !draft) return;
    const comparedDraft = draftFromCandidate(comparison);
    setDraft({
      ...comparedDraft,
      barcode: draft.barcode,
      name: comparison.issues.includes("missing_name") ? draft.name : comparedDraft.name,
      brand: draft.brand,
    });
    setCandidate(comparison);
    setComparison(null);
  };

  if (showLibrary) {
    return <ProductLibrary onClose={() => setShowLibrary(false)} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Scan</h2>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={() => { stopScan(); setShowLibrary(true); }}>
            <Library className="h-3.5 w-3.5" /> Library
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      </div>

      <video
        ref={videoRef}
        className={scanning ? "w-full rounded-xl" : "hidden"}
        playsInline
        muted
      />

      <div className="grid grid-cols-2 gap-3">
        <Button variant="outline" onClick={() => (scanning ? stopScan() : void startScan())} disabled={saving || bindingBarcode}>
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
            disabled={saving || bindingBarcode}
            onChange={(e) => {
              void parseLabel(e.target.files?.[0], false);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      <p className="text-[11px] leading-relaxed text-zinc-500">
        Label photos are processed by your configured vision provider and may leave this host. Parsing is stateless and never saves a product or meal.
      </p>

      {status && <p role="status" className="text-xs text-zinc-400">{status}</p>}
      {error && <p role="alert" className="text-xs leading-relaxed text-red-400">{error}</p>}

      {notFound && (
        <div className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <div className="flex items-start gap-2">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
            <div>
              <p className="text-sm font-medium">Barcode not found</p>
              <p className="mt-1 text-xs text-zinc-500">Open Food Facts authoritatively returned no product for {notFound}. Take a label photo to review it without saving automatically.</p>
            </div>
          </div>
        </div>
      )}

      {candidate && draft && !proposal && (
        <div className="space-y-4 rounded-xl border border-amber-900/60 bg-zinc-900/70 p-4">
          <div className="flex items-start gap-2">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
            <div>
              <h3 className="text-sm font-semibold">Review external candidate</h3>
              <p className="mt-1 text-xs leading-relaxed text-amber-200/70">
                {candidate.source === "open_food_facts" ? "Open Food Facts candidate" : "Vision label extraction"}. This is not in your product library and has not been saved.
              </p>
            </div>
          </div>

          {candidate.issues.length > 0 && (
            <p className="rounded-lg bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
              Check flagged fields: {candidate.issues.map(issueLabel).join(", ")}.
            </p>
          )}
          <ProductFields
            draft={draft}
            onChange={setDraft}
            onScanBarcode={candidate.source === "vision_label" && !candidate.barcode
              ? () => (scanning && scanPurpose === "attach" ? stopScan() : void startScan("attach"))
              : undefined}
            barcodeScanning={scanning && scanPurpose === "attach"}
            barcodeBinding={bindingBarcode}
            barcodeScanDisabled={saving}
          />

          {candidate.suggested_quantity_g && (
            <p className="rounded-lg bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300/90">
              Suggested portion from the label: {candidate.suggested_quantity_g} {candidate.serving_unit}. You can edit it in the Proposal Card before logging.
            </p>
          )}

          {candidate.source === "open_food_facts" && (
            <div className="space-y-2 rounded-lg border border-zinc-800 p-3">
              <p className="text-xs font-medium text-zinc-300">Optional label verification</p>
              <p className="text-[11px] text-zinc-500">Compare a downscaled label photo without saving either result. The image may leave this host.</p>
              <label className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-lg border border-zinc-700 px-3 text-xs font-medium hover:bg-zinc-800 active:scale-[0.98]">
                <ScanLine className="h-3.5 w-3.5" /> Compare label
                <input
                  type="file"
                  accept="image/*"
                  capture="environment"
                  className="hidden"
                  onChange={(event) => {
                    void parseLabel(event.target.files?.[0], true);
                    event.target.value = "";
                  }}
                />
              </label>
            </div>
          )}

          {comparison && (
            <div className="space-y-3 rounded-lg border border-emerald-900/50 bg-emerald-950/10 p-3">
              <div>
                <p className="text-xs font-semibold text-emerald-300">Stateless label comparison</p>
                <p className="mt-1 text-[11px] text-zinc-500">Label confidence {Math.round((comparison.confidence_score ?? 0) * 100)}%. Review the differences before replacing the editable values.</p>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs tabular-nums text-zinc-400 sm:grid-cols-3">
                {comparisonRows(draft, comparison).map(([label, current, labelValue]) => (
                  <p key={label}><span className="text-zinc-600">{label}</span> {current} → {labelValue}</p>
                ))}
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={useComparison}>Use label values</Button>
                <Button size="sm" variant="ghost" onClick={() => setComparison(null)}>Keep current</Button>
              </div>
            </div>
          )}

          <p className="text-[11px] text-zinc-500">
            Source if accepted: {sourceLabel(candidateDraftIsUnchanged(draft) ? draft.nutritionSource : "manual")}
            {!candidateDraftIsUnchanged(draft) && " (candidate fields were edited)"}
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            <Button variant="outline" onClick={logOnce} disabled={saving || bindingBarcode || scanning || scanStarting}>Log once</Button>
            <Button variant="outline" onClick={() => void save(false)} disabled={saving || bindingBarcode || scanning || scanStarting}>{saving ? "Saving..." : "Save product"}</Button>
            <Button onClick={() => void save(true)} disabled={saving || bindingBarcode || scanning || scanStarting}>{saving ? "Saving..." : "Save and log"}</Button>
          </div>
          <p className="text-[11px] text-zinc-600">Logging always opens the Proposal Card for final quantity review and confirmation.</p>
        </div>
      )}

      {proposal && (
        <div className="space-y-2">
          {proposalProvenance && (
            <p className="flex items-center gap-1.5 text-xs text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" /> {proposalProvenance}
            </p>
          )}
          <ProposalCard
            items={proposal}
            onDone={() => {
              setProposal(null);
              onClose();
            }}
          />
        </div>
      )}
    </div>
  );
}

function proposalFromProduct(
  product: Product,
  quantityG = 100,
  sourceType: ProposalCardItem["sourceType"] = "barcode",
): ProposalCardItem {
  return {
    name: (product.brand ? `${product.name} (${product.brand})` : product.name).slice(0, 255),
    per100: per100FromProduct(product),
    quantityG,
    quantityUnit: product.serving_unit.toLowerCase() === "ml" ? "ml" : "g",
    foodItemId: product.id,
    sourceType,
  };
}

function issueLabel(issue: ProductCandidate["issues"][number]): string {
  return issue.replace("missing_", "missing ").replace("calories", "calories");
}

function comparisonRows(draft: ProductDraft, comparison: ProductCandidate): [string, string, number][] {
  return [
    ["kcal", draft.calories, comparison.per100.calories],
    ["protein", draft.protein, comparison.per100.protein_g],
    ["carbs", draft.carbs, comparison.per100.carbs_g],
    ["fat", draft.fat, comparison.per100.fat_g],
    ["fiber", draft.fiber, comparison.per100.fiber_g],
  ];
}
