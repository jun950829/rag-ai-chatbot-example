"use server"

import { cookies } from "next/headers"
import { COOKIE_KEYS } from "@/constants/cookies"
import { defaultLocale, Locale } from "./config"

async function getUserLocale() {
  return (await cookies()).get(COOKIE_KEYS.LANGUAGE)?.value || defaultLocale
}

async function setUserLocale(locale: Locale) {
  ;(await cookies()).set(COOKIE_KEYS.LANGUAGE, locale)
}

export { getUserLocale, setUserLocale }
