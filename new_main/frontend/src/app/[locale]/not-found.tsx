import { getTranslations } from "next-intl/server"
import { Link } from "@/i18n/navigation"

export default async function NotFoundPage() {
  const t = await getTranslations()

  return (
    <div className="relative flex h-screen items-center justify-center overflow-hidden bg-gray-900">
      <div className="z-10 text-center text-white">
        <h1 className="text-[120px] font-medium leading-none">404</h1>
        <p className="mt-4 text-xl">Page not found</p>
        <p className="mt-6 max-w-sm text-gray-400">
          {t.rich("notfound", {
            br: (chunk) => <span><br className="hidden md:block" />{chunk}</span>,
          })}
        </p>
        <Link
          href="/"
          className="mt-8 inline-block rounded-full border border-white px-8 py-2.5 text-white hover:bg-white/10"
        >
          {t("common.goToHome")}
        </Link>
      </div>
    </div>
  )
}
