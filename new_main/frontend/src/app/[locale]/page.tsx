import type { Metadata } from "next"
import { NextPage } from "next"
import { getTranslations, setRequestLocale } from "next-intl/server"

import { Locale } from "@/i18n/config"
import { meta } from "@/lib/seo"
import { HomeView } from "@/views/home"

interface MetadataParam {
  params: Promise<{ locale: string }>
}

export async function generateMetadata({ params }: MetadataParam): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations()
  const keywords = t.raw("meta.home.keywords") as string[]

  return meta({
    locale: locale as Locale,
    pathname: "/",
    title: t("meta.home.title"),
    description: t("meta.home.description"),
    keywords,
  })
}

const HomePage: NextPage<{ params: Promise<{ locale: string }> }> = async ({ params }) => {
  const { locale } = await params
  setRequestLocale(locale)

  return <HomeView />
}

export default HomePage
