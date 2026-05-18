"use client"

import { useRouter } from "@/i18n/navigation"
import { Locale } from "@/i18n/config"
import { setUserLocale } from "@/i18n/locale"
import { queryClient } from "@/lib/query-client"

export function useLanguage() {
  const router = useRouter()

  async function switchLanguage(locale: Locale) {
    await setUserLocale(locale)
    queryClient.clear()
    router.refresh()
  }

  return { switchLanguage }
}
