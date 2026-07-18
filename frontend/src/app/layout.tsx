import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { LanguageProvider } from "@/i18n";
import { PhoneFrame } from "@/components/shell/PhoneFrame";

const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "NónAI — Tourist Shield",
  description:
    "Your AI travel companion in Vietnam. Instant fair-price checks, scam & ghost-tour detection, and one-tap emergency help with live translation.",
  manifest: "/manifest.json",
  applicationName: "NónAI",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "NónAI",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#EAF2E8" },
    { media: "(prefers-color-scheme: dark)", color: "#122420" },
  ],
};

// Set the theme before first paint to avoid a flash of the wrong theme.
const themeScript = `(function(){try{var t=localStorage.getItem('nonai.theme');if(!t){t='light';}document.documentElement.dataset.theme=t;}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={jakarta.variable} suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <LanguageProvider>
          <PhoneFrame>{children}</PhoneFrame>
        </LanguageProvider>
      </body>
    </html>
  );
}
