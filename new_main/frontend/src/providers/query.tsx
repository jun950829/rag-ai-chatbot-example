"use client"

import { QueryClientProvider } from "@tanstack/react-query"
import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import { useEffect } from "react"

import { ApiError } from "@/lib/agent"
import { queryClient } from "@/lib/query-client"

const shouldRetry = (failureCount: number, error: unknown): boolean => {
  if (error instanceof ApiError) {
    if (error.status === 0) return false
    if (error.status >= 400 && error.status < 500) {
      if (error.status === 408 || error.status === 429) return failureCount < 3
      return false
    }
    return failureCount < 3
  }
  return false
}

export const QueryProvider = ({ children }: { children: React.ReactNode }) => {
  useEffect(() => {
    queryClient.setDefaultOptions({
      queries: {
        retry: shouldRetry,
        retryDelay: (i: number) => Math.min(1000 * 2 ** i, 30000),
      },
      mutations: {
        retry: shouldRetry,
        retryDelay: (i: number) => Math.min(1000 * 2 ** i, 10000),
        onSuccess: (data: unknown) => {
          if (process.env.NODE_ENV === "development") {
            console.info("Mutation Success ✅:", JSON.stringify({ hasData: !!data }, null, 2))
          }
        },
      },
    })
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
