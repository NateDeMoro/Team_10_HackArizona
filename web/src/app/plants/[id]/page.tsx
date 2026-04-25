type Params = Promise<{ id: string }>;

export default async function PlantDetail({ params }: { params: Params }) {
  const { id } = await params;
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-2">
      <h1 className="text-xl font-semibold">Plant: {id}</h1>
      <p className="text-sm text-zinc-500">Detail page — implemented in Tier 5.</p>
    </main>
  );
}
