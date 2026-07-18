import type { LucideIcon } from "lucide-react";
import { Shield, Ambulance, Flame, Headphones } from "lucide-react";

export type Hotline = {
  id: string;
  name: string;
  number: string;
  icon: LucideIcon;
  tone: "police" | "ambulance" | "fire" | "hotline";
};

export const hotlines: Hotline[] = [
  { id: "police", name: "Police", number: "113", icon: Shield, tone: "police" },
  { id: "ambulance", name: "Ambulance", number: "115", icon: Ambulance, tone: "ambulance" },
  { id: "fire", name: "Fire & rescue", number: "114", icon: Flame, tone: "fire" },
  { id: "tourist", name: "Tourist hotline", number: "1800 1091", icon: Headphones, tone: "hotline" },
];

export type CallLine = {
  speaker: "you" | "operator";
  en: string;
  vi: string;
};

/** A 115 ambulance call, interpreted live by Nón. */
export const callScript: CallLine[] = [
  {
    speaker: "operator",
    vi: "Trung tâm cấp cứu 115 xin nghe.",
    en: "Emergency 115, how can I help you?",
  },
  {
    speaker: "you",
    en: "My friend fell and hurt his leg near Hoan Kiem Lake. We need an ambulance.",
    vi: "Bạn tôi bị ngã và đau chân gần Hồ Gươm. Chúng tôi cần xe cấp cứu.",
  },
  {
    speaker: "operator",
    vi: "Anh cho biết địa chỉ cụ thể được không?",
    en: "Can you tell me the exact location?",
  },
  {
    speaker: "you",
    en: "We're on the north side of Hoan Kiem Lake, next to the red Huc Bridge.",
    vi: "Chúng tôi ở phía bắc Hồ Gươm, cạnh cầu Thê Húc màu đỏ.",
  },
  {
    speaker: "operator",
    vi: "Xe cấp cứu đang tới, khoảng 8 phút. Anh giữ ấm và trấn an bạn nhé.",
    en: "An ambulance is on the way, about 8 minutes. Keep your friend warm and calm.",
  },
];
