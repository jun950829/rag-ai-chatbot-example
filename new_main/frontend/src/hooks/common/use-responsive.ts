"use client"

import { useEffect, useState } from "react"

interface Responsive {
  isMobile: boolean
  isTablet: boolean
  isDesktop: boolean
}

export function useResponsive(): Responsive {
  const [state, setState] = useState<Responsive>({
    isMobile: false,
    isTablet: false,
    isDesktop: true,
  })

  useEffect(() => {
    function update() {
      const width = window.innerWidth
      setState({
        isMobile: width < 768,
        isTablet: width >= 768 && width < 1280,
        isDesktop: width >= 1280,
      })
    }
    update()
    window.addEventListener("resize", update)
    return () => window.removeEventListener("resize", update)
  }, [])

  return state
}
