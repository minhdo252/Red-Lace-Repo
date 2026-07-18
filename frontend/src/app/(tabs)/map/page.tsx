import { MapFallback } from "./MapFallback";
import { MapGoogle } from "./MapGoogle";

/**
 * With a Google Maps key → interactive Google map (JS API) + Google Places
 * recommendations with photos. Without one → real Google map via iframe +
 * SerpApi list. NEXT_PUBLIC_ is inlined at build, so set the key before deploy.
 */
export default function MapPage() {
  const key = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY;
  return key ? <MapGoogle apiKey={key} /> : <MapFallback />;
}
