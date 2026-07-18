import type { TranslateTurn } from "./types";

/** A cyclo / taxi haggle that surfaces the classic "broken-meter" scam. */
export const conversation: TranslateTurn[] = [
  {
    speaker: "them",
    vi: "Đi Hồ Gươm hả? Năm trăm nghìn, xe đẹp máy lạnh nhé.",
    en: "Going to Hoan Kiem? Five hundred thousand — nice car, air-con.",
  },
  {
    speaker: "you",
    en: "That's quite high. Can you turn on the meter?",
    vi: "Hơi cao đấy. Anh bật đồng hồ được không?",
  },
  {
    speaker: "them",
    vi: "Đồng hồ hỏng rồi em ơi, với lại đang tắc đường. Năm trăm thôi.",
    en: "The meter's broken, and there's traffic anyway. Just five hundred.",
    scam: {
      pattern: "“Broken meter” + flat fare",
      advice:
        "A broken meter plus a high flat price is a classic overcharge. The metered fare here is about 60–90k₫. Decline politely and book a Grab or Xanh SM taxi instead.",
    },
  },
  {
    speaker: "you",
    en: "The metered fare is usually around 70 thousand. I'll book a Grab, thanks.",
    vi: "Đi đồng hồ thường chỉ khoảng bảy mươi nghìn. Em đặt Grab nhé, cảm ơn anh.",
  },
  {
    speaker: "them",
    vi: "Thôi được rồi, một trăm nghìn, lên xe đi.",
    en: "Alright, one hundred thousand — hop in.",
  },
];

export const summary = {
  topic: "Taxi fare to Hoan Kiem Lake",
  pricesHeard: [
    { label: "Driver's first price", value: "500,000₫", tone: "high" as const },
    { label: "Typical metered fare", value: "60–90,000₫", tone: "fair" as const },
    { label: "Final agreed", value: "100,000₫", tone: "mid" as const },
  ],
  scamCount: 1,
};
