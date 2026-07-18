"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { dictionaries, en, type Dict } from "./strings";
import {
  createSessionRequest,
  localeToNationality,
  localeToNativeLanguage,
} from "@/lib/api";

export type LocaleCode = keyof typeof dictionaries;

export type LocaleMeta = {
  code: LocaleCode;
  label: string; // native name
  english: string; // english name
  flag: string;
};

export const LOCALES: LocaleMeta[] = [
  { code: "en", label: "English", english: "English", flag: "🇬🇧" },
  { code: "zh", label: "中文", english: "Chinese", flag: "🇨🇳" },
  { code: "ko", label: "한국어", english: "Korean", flag: "🇰🇷" },
  { code: "ru", label: "Русский", english: "Russian", flag: "🇷🇺" },
  { code: "vi", label: "Tiếng Việt", english: "Vietnamese", flag: "🇻🇳" },
];

export type CountryMeta = {
  code: string;
  name: string;
  flag: string;
  embassy: string;
  embassyPhone: string;
};

/** Home countries (drives the SOS embassy card). */
export const COUNTRIES: CountryMeta[] = [
  { code: "KR", name: "South Korea", flag: "🇰🇷", embassy: "Embassy of the Republic of Korea, Hanoi", embassyPhone: "+84 24 3831 5110" },
  { code: "CN", name: "China", flag: "🇨🇳", embassy: "Embassy of China, Hanoi", embassyPhone: "+84 24 3845 3736" },
  { code: "RU", name: "Russia", flag: "🇷🇺", embassy: "Embassy of Russia, Hanoi", embassyPhone: "+84 24 3833 6991" },
  { code: "US", name: "United States", flag: "🇺🇸", embassy: "U.S. Embassy, Hanoi", embassyPhone: "+84 24 3850 5000" },
  { code: "GB", name: "United Kingdom", flag: "🇬🇧", embassy: "British Embassy, Hanoi", embassyPhone: "+84 24 3936 0500" },
];

/* deep-merge a partial locale over the English base ------------------- */
type AnyObj = Record<string, unknown>;
function isObj(v: unknown): v is AnyObj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function deepMerge<T>(base: T, override: unknown): T {
  if (!isObj(base) || !isObj(override)) return (override ?? base) as T;
  const out: AnyObj = { ...base };
  for (const key of Object.keys(override)) {
    out[key] = deepMerge((base as AnyObj)[key], (override as AnyObj)[key]);
  }
  return out as T;
}

export type ThemeMode = "light" | "dark";

type Ctx = {
  locale: LocaleCode;
  setLocale: (code: LocaleCode) => void;
  country: CountryMeta;
  setCountry: (c: CountryMeta) => void;
  dict: Dict;
  name: string;
  setName: (n: string) => void;
  theme: ThemeMode;
  setTheme: (t: ThemeMode) => void;
  toggleTheme: () => void;
  /** Backend session id (UUID), or null in mock mode. Lazily created. */
  sessionId: string | null;
  /** Create-or-return the backend session; null when no backend is configured. */
  ensureSession: () => Promise<string | null>;
  resetSession: () => void;
};

const LanguageContext = createContext<Ctx | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<LocaleCode>("en");
  const [country, setCountryState] = useState<CountryMeta>(COUNTRIES[0]);
  const [name, setName] = useState<string>("Minji");
  const [theme, setThemeState] = useState<ThemeMode>("light");
  const [sessionId, setSessionIdState] = useState<string | null>(null);

  // hydrate from localStorage
  useEffect(() => {
    const stored = localStorage.getItem("nonai.locale") as LocaleCode | null;
    const effectiveLocale = stored && stored in dictionaries ? stored : "en";
    if (stored && stored in dictionaries) setLocaleState(stored);
    const c = localStorage.getItem("nonai.country");
    if (c) {
      const found = COUNTRIES.find((x) => x.code === c);
      if (found) setCountryState(found);
    } else {
      // No saved country yet — default it from the chosen language so the backend
      // session (and the SOS embassy card) isn't stuck on the KR default.
      const derived = COUNTRIES.find((x) => x.code === localeToNationality(effectiveLocale));
      if (derived) setCountryState(derived);
    }
    const n = localStorage.getItem("nonai.name");
    if (n) setName(n);
    const th = localStorage.getItem("nonai.theme") as ThemeMode | null;
    if (th === "light" || th === "dark") setThemeState(th);
    const sid = localStorage.getItem("nonai.sessionId");
    if (sid) setSessionIdState(sid);
  }, []);

  const setTheme = useCallback((t: ThemeMode) => {
    setThemeState(t);
    localStorage.setItem("nonai.theme", t);
    document.documentElement.dataset.theme = t;
  }, []);
  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("nonai.theme", next);
      document.documentElement.dataset.theme = next;
      return next;
    });
  }, []);

  const setLocale = useCallback((code: LocaleCode) => {
    setLocaleState(code);
    localStorage.setItem("nonai.locale", code);
    // Language change invalidates the backend session (native_language differs).
    setSessionIdState(null);
    localStorage.removeItem("nonai.sessionId");
  }, []);

  const setCountry = useCallback((c: CountryMeta) => {
    setCountryState(c);
    localStorage.setItem("nonai.country", c.code);
    // Nationality change invalidates the backend session too.
    setSessionIdState(null);
    localStorage.removeItem("nonai.sessionId");
  }, []);

  const ensureSession = useCallback(async (): Promise<string | null> => {
    const existing = localStorage.getItem("nonai.sessionId");
    if (existing) {
      setSessionIdState(existing);
      return existing;
    }
    const res = await createSessionRequest({
      native_language: localeToNativeLanguage(locale),
      nationality: country.code,
    });
    if (res.session_id) {
      localStorage.setItem("nonai.sessionId", res.session_id);
      setSessionIdState(res.session_id);
      return res.session_id;
    }
    return null; // mock mode (no backend configured) — callers fall back to mock data
  }, [locale, country]);

  const resetSession = useCallback(() => {
    setSessionIdState(null);
    localStorage.removeItem("nonai.sessionId");
  }, []);

  const dict = useMemo(() => deepMerge(en, dictionaries[locale]), [locale]);

  const value: Ctx = {
    locale,
    setLocale,
    country,
    setCountry,
    dict,
    name,
    setName: (n: string) => {
      setName(n);
      localStorage.setItem("nonai.name", n);
    },
    theme,
    setTheme,
    toggleTheme,
    sessionId,
    ensureSession,
    resetSession,
  };

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useApp() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useApp must be used within LanguageProvider");
  return ctx;
}

/** Screen-scoped strings: `const t = useT("home"); t.greeting`. */
export function useT<K extends keyof Dict>(screen: K): Dict[K] {
  return useApp().dict[screen];
}
