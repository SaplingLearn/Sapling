"use client";

import React from "react";
import type { Cosmetic } from "@/lib/types";
import { Avatar } from "@/components/Avatar";

interface AvatarFrameProps {
  name: string;
  size?: number;
  img?: string;
  color?: string;
  frame?: Cosmetic | null;
}

export function AvatarFrame({ name, size = 48, img, color, frame }: AvatarFrameProps) {
  const overlay = size * 0.25;
  const box = Math.round(size + overlay);
  return (
    <div className="relative inline-block" style={{ width: size + overlay, height: size + overlay }}>
      <div className="absolute" style={{ top: overlay / 2, left: overlay / 2 }}>
        <Avatar name={name} size={size} img={img} color={color} />
      </div>
      {frame?.asset_url && (
        <img
          src={frame.asset_url}
          alt=""
          aria-hidden
          width={box}
          height={box}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className="absolute inset-0 w-full h-full pointer-events-none object-contain"
        />
      )}
    </div>
  );
}
