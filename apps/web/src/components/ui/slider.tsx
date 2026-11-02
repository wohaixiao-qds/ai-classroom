import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "../../lib/utils";

function Slider({
  className,
  defaultValue,
  value,
  min = 0,
  max = 100,
  ...props
}: React.ComponentProps<typeof SliderPrimitive.Root>) {
  return (
    <SliderPrimitive.Root
      data-slot="slider"
      defaultValue={defaultValue}
      value={value}
      min={min}
      max={max}
      className={cn(
        "relative flex w-full touch-none items-center py-1.5 select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <SliderPrimitive.Track
        data-slot="slider-track"
        className="relative h-1 w-full grow overflow-hidden rounded-full bg-muted-foreground/30"
      >
        <SliderPrimitive.Range
          data-slot="slider-range"
          className="absolute h-full bg-primary"
        />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        data-slot="slider-thumb"
        className="size-3 rounded-full border border-primary bg-primary shadow-sm transition-transform outline-none hover:scale-110 focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:pointer-events-none"
      />
    </SliderPrimitive.Root>
  );
}

export { Slider };
