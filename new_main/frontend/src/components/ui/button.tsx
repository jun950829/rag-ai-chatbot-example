import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { ButtonHTMLAttributes, forwardRef } from "react"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500/40 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "border border-gray-200 bg-white text-gray-800 shadow-sm hover:border-navy-500 hover:bg-navy-500/5 hover:text-navy-500 data-[selected=true]:border-navy-500 data-[selected=true]:bg-navy-500/5 data-[selected=true]:text-navy-500",
        primary: "bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800",
        send: "aspect-square rounded-full bg-red-500 text-white hover:bg-red-600 active:bg-red-700",
        chip: "rounded-full border border-gray-300 px-4 py-1.5 text-sm text-gray-700 shadow-sm hover:border-navy-500 hover:bg-navy-500/5 hover:text-navy-500 active:scale-95 data-[selected=true]:border-navy-500 data-[selected=true]:bg-navy-500/5 data-[selected=true]:text-navy-500",
        icon: "size-8 rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-800 active:bg-gray-200",
        ghost: "text-gray-700 hover:bg-gray-100 hover:text-gray-900 active:bg-gray-200",
        destructive: "bg-red-500 text-white hover:bg-red-600 active:bg-red-700",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-12 px-6",
        icon: "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
