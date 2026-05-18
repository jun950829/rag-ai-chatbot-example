import { defineRouting } from "next-intl/routing"
import { COOKIE_KEYS } from "@/constants/cookies"

export const routing = defineRouting({
  locales: ["en", "ko"],
  defaultLocale: "ko",
  localePrefix: "never",
  localeDetection: false,
  localeCookie: {
    name: COOKIE_KEYS.LANGUAGE,
    maxAge: 60 * 60 * 24 * 30,
    path: "/",
    sameSite: "lax",
    secure: true,
  },
})
