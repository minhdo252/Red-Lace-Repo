"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import {
  APIProvider,
  Map,
  AdvancedMarker,
  Pin,
  useMap,
  useMapsLibrary,
} from "@vis.gl/react-google-maps";
import { ChevronLeft, LocateFixed, Star, Navigation, Loader2 } from "lucide-react";
import { useApp, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { nearbyFilters, type NearbyPlace } from "@/mocks/nearby";

const HOAN_KIEM = { lat: 21.0287, lng: 105.8524 };
type LatLng = { lat: number; lng: number };

function haversine(a: LatLng, b: LatLng) {
  const R = 6371000;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((a.lat * Math.PI) / 180) * Math.cos((b.lat * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}
function fmtDist(m: number) {
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
}

export function MapGoogle({ apiKey }: { apiKey: string }) {
  const t = useT("map");
  const router = useRouter();
  const { theme } = useApp();

  const [center, setCenter] = useState<LatLng>(HOAN_KIEM);
  const [myLoc, setMyLoc] = useState<LatLng | null>(null);
  const [filter, setFilter] = useState(nearbyFilters[0]);
  const [results, setResults] = useState<NearbyPlace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);

  const locate = () => {
    if (!navigator.geolocation) {
      setError("Location isn't available on this device.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setMyLoc(c);
        setCenter(c);
        setLocating(false);
      },
      () => {
        setError("Couldn't get your location — showing Hoàn Kiếm.");
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  };

  return (
    <APIProvider apiKey={apiKey}>
      <div className="relative flex h-full flex-col bg-bg text-ink">
        {/* header */}
        <header className="flex items-center gap-2 px-4 pb-2 pt-[max(env(safe-area-inset-top),0.75rem)]">
          <button
            onClick={() => router.push("/home")}
            aria-label="Back"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-surface text-ink shadow-[var(--shadow-soft)] active:scale-95"
          >
            <ChevronLeft size={22} />
          </button>
          <div className="flex-1">
            <h1 className="font-display text-lg font-extrabold leading-none tracking-tight text-ink">
              {t.title}
            </h1>
            <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-mute">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-fair" />
              Live · Google Maps
            </p>
          </div>
          <button
            onClick={locate}
            aria-label="Use my location"
            className="inline-flex h-10 items-center gap-1.5 rounded-full bg-accent px-3.5 text-sm font-semibold text-on-brand shadow-[var(--shadow-soft)] active:scale-95"
          >
            {locating ? <Loader2 size={17} className="animate-spin" /> : <LocateFixed size={17} />}
            GPS
          </button>
        </header>

        <div className="scroll-area no-scrollbar flex-1 overflow-y-auto px-4 pb-[max(env(safe-area-inset-bottom),1rem)]">
          {/* interactive google map */}
          <div className="relative h-[240px] overflow-hidden rounded-[var(--radius-lg)] border border-line shadow-[var(--shadow-soft)]">
            <Map
              key={theme}
              mapId="DEMO_MAP_ID"
              className="h-full w-full"
              defaultCenter={HOAN_KIEM}
              defaultZoom={15}
              gestureHandling="greedy"
              disableDefaultUI
              reuseMaps
              colorScheme={theme === "dark" ? "DARK" : "LIGHT"}
            >
              {myLoc && (
                <AdvancedMarker position={myLoc} title="You are here">
                  <Pin background="#2F8F7F" borderColor="#ffffff" glyphColor="#ffffff" />
                </AdvancedMarker>
              )}
              {results.map(
                (p) =>
                  p.lat != null &&
                  p.lng != null && (
                    <AdvancedMarker key={p.id} position={{ lat: p.lat, lng: p.lng }} title={p.name}>
                      <Pin background="#E0A020" borderColor="#7A5A10" glyphColor="#5A4200" />
                    </AdvancedMarker>
                  ),
              )}
              <MapController center={center} />
            </Map>
          </div>

          <PlacesSearch
            center={center}
            query={filter.q}
            onLoading={() => setLoading(true)}
            onDone={(list) => {
              setResults(list);
              setLoading(false);
              setError(null);
            }}
            onError={(m) => {
              setError(m);
              setResults([]);
              setLoading(false);
            }}
          />

          {error && <p className="mt-2 text-xs text-ink-mute">{error}</p>}

          {/* filter chips */}
          <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto">
            {nearbyFilters.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f)}
                className={cn(
                  "shrink-0 rounded-full px-3.5 py-2 text-sm font-semibold transition-colors active:scale-95",
                  f.key === filter.key
                    ? "bg-accent text-on-brand"
                    : "bg-surface text-ink-soft shadow-[var(--shadow-soft)]",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div className="mt-4 flex items-center justify-between">
            <h2 className="font-display text-base font-bold text-ink">{t.nearbyTitle}</h2>
            {loading && <Loader2 size={16} className="animate-spin text-ink-mute" />}
          </div>

          <div className="mt-2 space-y-2.5">
            {results.map((p, i) => (
              <PlaceRow key={p.id} p={p} center={center} index={i} />
            ))}
            {!loading && !results.length && (
              <p className="py-8 text-center text-sm text-ink-mute">No places found nearby.</p>
            )}
          </div>
        </div>
      </div>
    </APIProvider>
  );
}

/** Pans the live map when the search center changes (e.g. after GPS). */
function MapController({ center }: { center: LatLng }) {
  const map = useMap();
  useEffect(() => {
    if (map) map.panTo(center);
  }, [map, center]);
  return null;
}

/** Runs a Google Places text search around `center` and lifts normalized results up. */
function PlacesSearch({
  center,
  query,
  onLoading,
  onDone,
  onError,
}: {
  center: LatLng;
  query: string;
  onLoading: () => void;
  onDone: (list: NearbyPlace[]) => void;
  onError: (msg: string) => void;
}) {
  const placesLib = useMapsLibrary("places");
  const reqId = useRef(0);

  useEffect(() => {
    if (!placesLib) return;
    const id = ++reqId.current;
    onLoading();
    (async () => {
      try {
        const { places } = await placesLib.Place.searchByText({
          textQuery: query,
          fields: [
            "id",
            "displayName",
            "location",
            "rating",
            "userRatingCount",
            "photos",
            "formattedAddress",
            "primaryTypeDisplayName",
          ],
          locationBias: { center, radius: 1500 },
          maxResultCount: 12,
          language: "en",
        });
        if (id !== reqId.current) return;
        const list: NearbyPlace[] = (places ?? []).map((p, i) => ({
          id: p.id ?? `g-${i}`,
          name: p.displayName ?? "Place",
          category: p.primaryTypeDisplayName ?? "Place",
          rating: p.rating ?? undefined,
          reviews: p.userRatingCount ?? undefined,
          address: p.formattedAddress ?? undefined,
          photo: p.photos?.[0]?.getURI({ maxWidth: 240 }),
          lat: p.location?.lat(),
          lng: p.location?.lng(),
        }));
        onDone(list);
      } catch (e) {
        if (id !== reqId.current) return;
        onError(e instanceof Error ? e.message : "Google Places error");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placesLib, center, query]);

  return null;
}

function PlaceRow({ p, center, index }: { p: NearbyPlace; center: LatLng; index: number }) {
  const dist =
    p.lat != null && p.lng != null ? fmtDist(haversine(center, { lat: p.lat, lng: p.lng })) : null;
  const dir =
    p.lat != null && p.lng != null
      ? `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lng}`
      : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(p.name)}`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.3), ease: [0.16, 1, 0.3, 1] }}
      className="flex items-center gap-3 rounded-[var(--radius-card)] bg-surface p-2.5 shadow-[var(--shadow-soft)]"
    >
      {p.photo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={p.photo}
          alt={p.name}
          loading="lazy"
          className="h-16 w-16 shrink-0 rounded-xl object-cover"
        />
      ) : (
        <div className="grid h-16 w-16 shrink-0 place-items-center rounded-xl bg-surface-2 text-ink-mute">
          <Navigation size={18} />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold text-ink">{p.name}</p>
        <p className="truncate text-xs text-ink-mute">{p.category}</p>
        <div className="mt-1 flex items-center gap-2 text-xs">
          {p.rating != null && (
            <span className="inline-flex items-center gap-1 font-semibold text-straw-deep">
              <Star size={12} className="fill-current" />
              {p.rating}
              {p.reviews != null && (
                <span className="font-normal text-ink-mute">({p.reviews.toLocaleString()})</span>
              )}
            </span>
          )}
          {dist && <span className="text-ink-mute">· {dist}</span>}
        </div>
      </div>
      <a
        href={dir}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Directions to ${p.name}`}
        className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent/12 text-accent active:scale-95"
      >
        <Navigation size={18} />
      </a>
    </motion.div>
  );
}
