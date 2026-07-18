"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { ChevronLeft, LocateFixed, Star, Navigation, MapPin, Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { nearbyFilters, type NearbyPlace, type NearbyResponse } from "@/mocks/nearby";

const HOAN_KIEM = { lat: 21.0287, lng: 105.8524 };

function haversine(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
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

/** Map screen without a Google Maps key — real Google map via iframe + SerpApi list. */
export function MapFallback() {
  const t = useT("map");
  const router = useRouter();

  const [center, setCenter] = useState(HOAN_KIEM);
  const [myLoc, setMyLoc] = useState<{ lat: number; lng: number } | null>(null);
  const [filter, setFilter] = useState(nearbyFilters[0]);
  const [data, setData] = useState<NearbyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const reqId = useRef(0);

  const load = useCallback(
    async (c: { lat: number; lng: number }, q: string) => {
      const id = ++reqId.current;
      setLoading(true);
      try {
        const res = await fetch(`/api/nearby?lat=${c.lat}&lng=${c.lng}&q=${encodeURIComponent(q)}`);
        const json: NearbyResponse = await res.json();
        if (id === reqId.current) setData(json);
      } catch {
        if (id === reqId.current) setData({ source: "mock", places: [] });
      } finally {
        if (id === reqId.current) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    load(center, filter.q);
  }, [center, filter, load]);

  const locate = () => {
    if (!navigator.geolocation) {
      setGeoError("Location isn't available on this device.");
      return;
    }
    setLocating(true);
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setMyLoc(c);
        setCenter(c);
        setLocating(false);
      },
      () => {
        setGeoError("Couldn't get your location — showing Hoàn Kiếm.");
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  };

  const mapSrc = `https://www.google.com/maps?q=${center.lat},${center.lng}&z=15&output=embed`;
  const places = data?.places ?? [];
  const live = data?.source === "serpapi";

  return (
    <div className="relative flex h-full flex-col bg-bg text-ink">
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
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", live ? "bg-fair" : "bg-straw-deep")} />
            {live ? "Live · Google Maps" : "Sample data"}
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
        <div className="relative overflow-hidden rounded-[var(--radius-lg)] border border-line shadow-[var(--shadow-soft)]">
          <iframe
            key={mapSrc}
            title="Google Map"
            src={mapSrc}
            className="h-[240px] w-full"
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
          />
          {myLoc && (
            <span className="pointer-events-none absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-surface/90 px-2.5 py-1 text-xs font-semibold text-ink shadow-[var(--shadow-soft)] backdrop-blur">
              <MapPin size={12} className="text-accent" /> You are here
            </span>
          )}
        </div>

        {geoError && <p className="mt-2 text-xs text-ink-mute">{geoError}</p>}

        <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto">
          {nearbyFilters.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f)}
              className={cn(
                "shrink-0 rounded-full px-3.5 py-2 text-sm font-semibold transition-colors active:scale-95",
                f.key === filter.key ? "bg-accent text-on-brand" : "bg-surface text-ink-soft shadow-[var(--shadow-soft)]",
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
          {places.map((p, i) => (
            <PlaceRow key={p.id} p={p} center={center} index={i} />
          ))}
          {!loading && !places.length && (
            <p className="py-8 text-center text-sm text-ink-mute">No places found nearby.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function PlaceRow({
  p,
  center,
  index,
}: {
  p: NearbyPlace;
  center: { lat: number; lng: number };
  index: number;
}) {
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
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={p.photo || "/content/hanoi.jpg"}
        alt={p.name}
        loading="lazy"
        className="h-16 w-16 shrink-0 rounded-xl object-cover"
      />
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
