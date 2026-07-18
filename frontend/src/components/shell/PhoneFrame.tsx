/**
 * On phones (< sm) the app is full-bleed.
 * On desktop it sits inside a centred device frame so the same build doubles
 * as the "web" view — with a soft sage stage behind it.
 */
export function PhoneFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="phone-stage relative grid min-h-dvh w-full place-items-center bg-bg sm:bg-[radial-gradient(120%_120%_at_50%_0%,#eef4ec_0%,#dfe9db_45%,#cfe0cb_100%)] sm:py-8">
      {/* desktop-only ambient brand watermark */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 hidden overflow-hidden sm:block"
      >
        <div className="absolute -right-24 top-16 h-72 w-72 rounded-full bg-moss/10 blur-3xl" />
        <div className="absolute -left-20 bottom-10 h-64 w-64 rounded-full bg-teal/10 blur-3xl" />
      </div>

      <div className="phone-device relative flex h-dvh w-full max-w-[440px] flex-col overflow-hidden bg-bg sm:h-[min(880px,calc(100dvh-4rem))] sm:w-[404px] sm:rounded-[2.9rem] sm:border-[10px] sm:border-[#10201b] sm:shadow-[0_40px_90px_-30px_rgba(20,40,34,0.55)]">
        {/* fake dynamic island — desktop only */}
        <div className="pointer-events-none absolute left-1/2 top-2 z-50 hidden h-6 w-28 -translate-x-1/2 rounded-full bg-[#10201b] sm:block" />
        {children}
      </div>
    </div>
  );
}
