"use client"

import { Button } from "@/components/ui/button"

export default function Error() {
  return (
    <div className="relative flex h-screen items-center justify-center overflow-hidden bg-gray-900">
      <div className="z-10 text-center text-white">
        <h1 className="text-[120px] font-medium leading-none">500</h1>
        <p className="mt-4 text-xl">Server error</p>
        <p className="mt-6 text-gray-400">Sorry, something went wrong.</p>
        <Button
          variant="ghost"
          className="mt-8 border border-white text-white hover:bg-white/10"
          onClick={() => window?.history.back()}
        >
          Go Back
        </Button>
      </div>
    </div>
  )
}
