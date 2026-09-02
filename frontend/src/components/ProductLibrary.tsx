import { useDeferredValue, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Library, Pencil, Plus, Search, X } from "lucide-react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import {
  archiveProduct,
  createProduct,
  draftFromProduct,
  emptyProductDraft,
  listProducts,
  productFingerprint,
  sourceLabel,
  stableMutation,
  updateProduct,
  validateProductDraft,
  type Product,
  type ProductDraft,
  type StableMutation,
} from "../lib/products";

const inputClass =
  "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-600 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60";

export function ProductFields({
  draft,
  onChange,
  lockBarcode = false,
}: {
  draft: ProductDraft;
  onChange: (draft: ProductDraft) => void;
  lockBarcode?: boolean;
}) {
  const set = (key: keyof ProductDraft, value: string) => onChange({ ...draft, [key]: value });
  const nutrient = (
    key: "calories" | "protein" | "carbs" | "fat" | "fiber",
    label: string,
    unit: string,
  ) => (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-zinc-400">{label}</span>
      <div className="relative">
        <input
          className={`${inputClass} pr-12 tabular-nums`}
          inputMode="decimal"
          aria-label={`${label} per 100 grams or milliliters`}
          value={draft[key]}
          onChange={(event) => set(key, event.target.value)}
        />
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-zinc-600">
          {unit}
        </span>
      </div>
    </label>
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1.5 sm:col-span-2">
          <span className="text-xs font-medium text-zinc-300">Product name</span>
          <input
            className={inputClass}
            maxLength={255}
            value={draft.name}
            onChange={(event) => set("name", event.target.value)}
          />
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-400">Brand</span>
          <input
            className={inputClass}
            maxLength={255}
            value={draft.brand}
            onChange={(event) => set("brand", event.target.value)}
          />
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-400">Barcode</span>
          <input
            className={inputClass}
            maxLength={64}
            disabled={lockBarcode}
            value={draft.barcode}
            onChange={(event) => set("barcode", event.target.value)}
          />
          {lockBarcode && <span className="text-[11px] text-zinc-600">Barcode cannot be changed after acceptance.</span>}
        </label>
      </div>

      <fieldset className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
        <legend className="px-1 text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500">
          Nutrition per 100 g/ml
        </legend>
        <div className="grid gap-3 sm:grid-cols-2">
          {nutrient("calories", "Calories", "kcal")}
          {nutrient("protein", "Protein", "g")}
          {nutrient("carbs", "Carbohydrates", "g")}
          {nutrient("fat", "Fat", "g")}
          {nutrient("fiber", "Fiber", "g")}
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-400">Serving unit</span>
            <input
              className={inputClass}
              maxLength={32}
              value={draft.servingUnit}
              onChange={(event) => set("servingUnit", event.target.value)}
            />
          </label>
        </div>
      </fieldset>
    </div>
  );
}

function ProductEditor({
  product,
  onSaved,
  onCancel,
}: {
  product: Product | null;
  onSaved: (product: Product) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ProductDraft>(() =>
    product ? draftFromProduct(product) : emptyProductDraft(),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mutation = useRef<StableMutation | null>(null);

  const save = async () => {
    const validated = validateProductDraft(draft);
    if (!validated.value) {
      setError(validated.error);
      return;
    }
    const fingerprint = productFingerprint({
      operation: product ? "update" : "create",
      productId: product?.id ?? null,
      expectedVersion: product?.version ?? null,
      value: validated.value,
    });
    mutation.current = stableMutation(mutation.current, fingerprint);
    setSaving(true);
    setError(null);
    try {
      const saved = product
        ? await updateProduct(product, validated.value, mutation.current.id)
        : await createProduct(validated.value, mutation.current.id);
      mutation.current = null;
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="space-y-4 border-emerald-900/60">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{product ? "Edit accepted product" : "Add product manually"}</h3>
          <p className="mt-1 text-xs text-zinc-500">
            {product ? `Saving checks version ${product.version} to prevent overwriting newer edits.` : "Nothing is added until you save this review."}
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={onCancel} aria-label="Close product editor">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <ProductFields draft={draft} onChange={setDraft} lockBarcode={Boolean(product)} />
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? "Saving..." : product ? "Save changes" : "Accept product"}
        </Button>
      </div>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    </Card>
  );
}

export function ProductLibrary({
  onClose,
  onSelect,
}: {
  onClose?: () => void;
  onSelect?: (product: Product) => void;
}) {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Product | null>(null);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [archiving, setArchiving] = useState(false);
  const archiveMutation = useRef<StableMutation | null>(null);
  const products = useQuery({
    queryKey: ["products", deferredQuery],
    queryFn: () => listProducts(deferredQuery),
    placeholderData: (previous) => previous,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["products"] });
  };

  const archive = async () => {
    if (!archiveTarget) return;
    const fingerprint = productFingerprint({
      operation: "archive",
      productId: archiveTarget.id,
      expectedVersion: archiveTarget.version,
    });
    archiveMutation.current = stableMutation(archiveMutation.current, fingerprint);
    setArchiving(true);
    setArchiveError(null);
    try {
      await archiveProduct(archiveTarget, archiveMutation.current.id);
      archiveMutation.current = null;
      setArchiveTarget(null);
      await refresh();
    } catch (err) {
      setArchiveError(err instanceof Error ? err.message : String(err));
    } finally {
      setArchiving(false);
    }
  };

  if (editing) {
    return (
      <ProductEditor
        key={editing === "new" ? "new" : `${editing.id}:${editing.version}`}
        product={editing === "new" ? null : editing}
        onCancel={() => setEditing(null)}
        onSaved={(saved) => {
          setEditing(null);
          void refresh();
          onSelect?.(saved);
        }}
      />
    );
  }

  return (
    <section className="space-y-4" aria-labelledby="product-library-title">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="product-library-title" className="flex items-center gap-2 text-base font-semibold">
            <Library className="h-4 w-4 text-emerald-400" /> Product library
          </h2>
          <p className="mt-1 text-xs text-zinc-500">Accepted active products only. Every source was reviewed before saving.</p>
        </div>
        {onClose && <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <label className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-zinc-600" />
          <span className="sr-only">Search accepted products</span>
          <input
            type="search"
            className={`${inputClass} pl-9`}
            placeholder="Search by product name"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <Button onClick={() => setEditing("new")}>
          <Plus className="h-4 w-4" /> Add product
        </Button>
      </div>

      {products.isPending && <p className="text-sm text-zinc-500">Loading products...</p>}
      {products.error && <p role="alert" className="text-sm text-red-400">{products.error.message}</p>}
      {products.data?.length === 0 && (
        <Card className="py-8 text-center text-sm text-zinc-500">
          {deferredQuery ? "No accepted products match this search." : "No accepted products yet."}
        </Card>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        {products.data?.map((product) => (
          <Card key={product.id} className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <button
                type="button"
                className={`min-w-0 text-left ${onSelect ? "cursor-pointer" : "cursor-default"}`}
                onClick={() => onSelect?.(product)}
                disabled={!onSelect}
              >
                <p className="truncate text-sm font-semibold text-zinc-100">{product.name}</p>
                <p className="truncate text-xs text-zinc-500">{product.brand || "No brand"}{product.barcode ? ` · ${product.barcode}` : ""}</p>
              </button>
              <div className="flex shrink-0 gap-1">
                <Button variant="ghost" size="icon" onClick={() => setEditing(product)} aria-label={`Edit ${product.name}`}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => { setArchiveError(null); setArchiveTarget(product); }} aria-label={`Archive ${product.name}`}>
                  <Archive className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <p className="text-xs tabular-nums text-zinc-400">
              {product.calories_per_100} kcal · {product.protein_per_100}g protein · {product.carbs_per_100}g carbs · {product.fat_per_100}g fat
            </p>
            <p className="text-[11px] text-emerald-400/80">{sourceLabel(product.nutrition_source)} · version {product.version}</p>
          </Card>
        ))}
      </div>

      {archiveTarget && (
        <div className="rounded-xl border border-red-900/60 bg-red-950/20 p-4" role="alertdialog" aria-labelledby="archive-title" aria-describedby="archive-description">
          <h3 id="archive-title" className="text-sm font-semibold text-red-200">Archive {archiveTarget.name}?</h3>
          <p id="archive-description" className="mt-1 text-xs text-zinc-400">It will stop appearing in active searches and barcode resolution. Existing meal logs remain unchanged.</p>
          <div className="mt-3 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="ghost" onClick={() => setArchiveTarget(null)} disabled={archiving}>Keep product</Button>
            <Button variant="destructive" onClick={() => void archive()} disabled={archiving}>{archiving ? "Archiving..." : "Archive product"}</Button>
          </div>
          {archiveError && <p className="mt-2 text-xs text-red-400">{archiveError}</p>}
        </div>
      )}
    </section>
  );
}
