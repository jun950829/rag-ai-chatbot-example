import type { Metadata } from "next"
import { Locale } from "@/i18n/config"

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"

const HREFLANG: Record<Locale, string> = {
  ko: "ko-KR",
  en: "en-US",
}

const APP_NAME: Record<Locale, string> = {
  ko: "Exmatch",
  en: "Exmatch",
}

const DEFAULT_DESCRIPTION: Record<Locale, string> = {
  ko: "Exmatch AI 어시스턴트",
  en: "Exmatch AI Assistant",
}

function abs(path: string) {
  return `${SITE_URL}${path}`
}

export function meta(opts: {
  locale: Locale
  pathname: string
  title: string
  description?: string
  image?: string
  keywords?: string[]
  noIndex?: boolean
  canonicalOverride?: string
  type?: "website" | "article" | "profile"
}): Metadata {
  const { locale, pathname, title, description, image, keywords, noIndex, canonicalOverride, type = "website" } = opts

  const canonicalPath = canonicalOverride ?? pathname
  const fullTitle = `${title} | ${APP_NAME[locale]}`
  const desc = description ?? DEFAULT_DESCRIPTION[locale]
  const ogImage = image ? (image.startsWith("http") ? image : abs(image)) : abs("/og-image.png")

  return {
    metadataBase: new URL(SITE_URL),
    title: fullTitle,
    description: desc,
    keywords: keywords ?? [],
    robots: noIndex
      ? { index: false, follow: false }
      : { index: true, follow: true },

    alternates: {
      canonical: canonicalPath,
      languages: {
        [HREFLANG.ko]: abs(`/ko${pathname}`),
        [HREFLANG.en]: abs(`/en${pathname}`),
        "x-default": abs(`/ko${pathname}`),
      },
    },

    openGraph: {
      type,
      title: fullTitle,
      description: desc,
      siteName: APP_NAME[locale],
      url: abs(canonicalPath),
      locale: HREFLANG[locale],
      images: [{ url: ogImage, width: 1200, height: 630, alt: fullTitle }],
    },

    twitter: {
      card: "summary_large_image",
      title: fullTitle,
      description: desc,
      images: [ogImage],
    },
  }
}

export function generateOrganizationSchema(locale: Locale) {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: APP_NAME[locale],
    url: SITE_URL,
    description: DEFAULT_DESCRIPTION[locale],
    contactPoint: {
      "@type": "ContactPoint",
      contactType: "Customer Service",
      availableLanguage: ["Korean", "English"],
    },
  }
}

export function generateWebsiteSchema(locale: Locale) {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: APP_NAME[locale],
    url: SITE_URL,
    description: DEFAULT_DESCRIPTION[locale],
    inLanguage: locale === "ko" ? "ko-KR" : "en-US",
  }
}
