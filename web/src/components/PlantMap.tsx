"use client";

import Link from "next/link";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";

import type { AlertLevel, Plant } from "@/lib/api";
import { ALERT_COPY, ALERT_HEX } from "@/lib/format";

// One per modeled plant; absent when the forecast endpoint failed for
// that plant. The map shows placeholder grey for unmodeled plants and
// for modeled plants whose forecast didn't load.
export type PlantSummary = {
  level: AlertLevel;
  pointPct: number;
};

type Props = {
  plants: Plant[];
  summaries: Record<string, PlantSummary>;
};

// Continental US bounds; zoom 4 fits CONUS comfortably without showing
// huge ocean margins on a typical desktop layout.
const CENTER: [number, number] = [39.5, -98.35];
const ZOOM = 4;

const PLACEHOLDER_HEX = "#9ca3af"; // zinc-400

export default function PlantMap({ plants, summaries }: Props) {
  return (
    <MapContainer
      center={CENTER}
      zoom={ZOOM}
      // Inline pixel height: Leaflet measures the container at mount time
      // and won't render tiles if the height resolves to 0 — Tailwind
      // arbitrary classes occasionally hydrate after that measurement
      // when the map ships in a dynamic chunk.
      style={{ height: 520, width: "100%" }}
      className="rounded-xl border border-[var(--ua-navy)]/30 shadow-sm"
      scrollWheelZoom={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {plants.map((plant) => {
        const summary = plant.modeled ? summaries[plant.id] : undefined;
        const color = summary ? ALERT_HEX[summary.level] : PLACEHOLDER_HEX;
        return (
          <CircleMarker
            key={plant.id}
            center={[plant.lat, plant.lon]}
            radius={plant.modeled ? 9 : 5}
            pathOptions={{
              color,
              fillColor: color,
              fillOpacity: plant.modeled ? 0.85 : 0.35,
              weight: plant.modeled ? 2 : 1,
            }}
          >
            <Popup>
              <div className="flex flex-col gap-1 text-xs">
                <p className="font-semibold">{plant.display_name}</p>
                <p className="text-zinc-500">
                  {[plant.operator, plant.state].filter(Boolean).join(" · ")}
                </p>
                {plant.modeled ? (
                  <>
                    {summary ? (
                      <p>
                        7-day risk:{" "}
                        <span style={{ color }} className="font-medium">
                          {ALERT_COPY[summary.level]}
                        </span>
                        {` (${summary.pointPct.toFixed(1)}%)`}
                      </p>
                    ) : null}
                    <Link
                      href={`/plants/${plant.id}`}
                      className="text-sky-600 hover:underline"
                    >
                      Open detail →
                    </Link>
                  </>
                ) : (
                  <p className="text-zinc-500">Model coming soon.</p>
                )}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
